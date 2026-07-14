"""Selective-prediction risk model for always-on property estimates.

The point model must value every scoreable property, but it need not pretend
that every estimate is equally reliable.  This module learns expected absolute
log error on a held-out slice using only model disagreement, raw quantile
width, evidence density, property state, and record-quality signals.  It never
changes the point estimate and never uses demographic features.

Training discipline:

* GBM point arms train on the fit slice.
* the risk model trains on the first 80% of the point model's validation slice;
* risk-tier thresholds use the remaining 20% of validation;
* promotion and the risk-coverage curve use the untouched out-of-time test.

If the test audit cannot show monotone error separation, the artifact is kept
as a rejected experiment and scoring returns ``standard`` risk for everyone.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure.models.baseline import CATBOOST_MODEL_FILE, catboost_frame
from philly_fair_measure.models.conformal import split_frames
from philly_fair_measure.models.metrics import evaluate_estimates
from philly_fair_measure.models.scoring import (
    _lightgbm_arm_log,
    run_params,
    score_point,
    score_quantile_heads,
)

logger = logging.getLogger(__name__)

RISK_MODEL_FILE: Final = "risk_model.txt"
RISK_METADATA_FILE: Final = "risk_model.json"
RISK_EVALUATION_FILE: Final = "risk_evaluation.parquet"
RiskTier = Literal["standard", "elevated", "high"]

MIN_RISK_VALIDATION_ROWS: Final = 500
MIN_RISK_TEST_ROWS: Final = 300

RISK_COLUMNS: Final = (
    "mkt_knn_n",
    "mkt_knn_mean_dist_m",
    "mkt_block_roll_n",
    "state_active_work_evidence",
    "state_distress_evidence",
    "state_measurement_conflict_evidence",
    "state_competing_evidence",
    "quality_characteristic_conflict_score",
    "quality_characteristic_outlier",
    "quality_area_outlier",
    "quality_zero_bed_bath_conflict",
    "char_area_conflict",
)
RISK_FEATURE_NAMES: Final = (
    "raw_cqr_width_log",
    "gbm_arm_disagreement_log",
    *RISK_COLUMNS,
)


@dataclass(frozen=True)
class RiskModelResult:
    run_dir: Path
    promoted: bool
    metadata: dict[str, object]
    evaluation: pl.DataFrame


def _catboost_arm_log(run_dir: Path, frame: pl.DataFrame) -> npt.NDArray[np.float64]:
    from catboost import CatBoostRegressor

    params = run_params(run_dir)
    model = CatBoostRegressor()
    model.load_model(str(run_dir / CATBOOST_MODEL_FILE))
    return np.asarray(
        model.predict(
            catboost_frame(frame, params["numeric_features"], params["categorical_features"])
        ),
        dtype=np.float64,
    )


def _risk_matrix(run_dir: Path, frame: pl.DataFrame) -> npt.NDArray[np.float64]:
    quantiles = score_quantile_heads(run_dir, frame)
    if quantiles is None:
        raw_width = np.zeros(frame.height)
    else:
        raw_width = np.maximum(quantiles[1] - quantiles[0], 0.0)
    lgb_log = _lightgbm_arm_log(run_dir, frame)
    cat_log = _catboost_arm_log(run_dir, frame)
    columns: list[npt.NDArray[np.float64]] = [raw_width, np.abs(lgb_log - cat_log)]
    for name in RISK_COLUMNS:
        if name in frame.columns:
            values = frame[name].cast(pl.Float64, strict=False).fill_null(0.0).to_numpy()
        else:
            values = np.zeros(frame.height)
        columns.append(np.asarray(values, dtype=np.float64))
    return np.column_stack(columns)


def _reference_log_price(run_dir: Path, frame: pl.DataFrame) -> npt.NDArray[np.float64]:
    out = np.log(frame["sale_price"].to_numpy())
    if run_params(run_dir).get("time_adjusted"):
        out = out + frame["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    return np.asarray(out, dtype=np.float64)


def _point_log(run_dir: Path, frame: pl.DataFrame) -> npt.NDArray[np.float64]:
    return np.log(score_point(run_dir, frame))


def _tiers(score: np.ndarray, elevated: float, high: float) -> npt.NDArray[np.str_]:
    return np.where(score >= high, "high", np.where(score >= elevated, "elevated", "standard"))


def _risk_evaluation(
    score: np.ndarray,
    actual_log: np.ndarray,
    point_log: np.ndarray,
    elevated: float,
    high: float,
) -> pl.DataFrame:
    abs_error = np.abs(actual_log - point_log)
    tiers = _tiers(score, elevated, high)
    rows: list[dict[str, object]] = []
    for tier in ("standard", "elevated", "high"):
        mask = tiers == tier
        metrics = evaluate_estimates(np.exp(point_log[mask]), np.exp(actual_log[mask]))
        mean_score = float(score[mask].mean()) if np.any(mask) else None
        mean_error = float(abs_error[mask].mean()) if np.any(mask) else None
        rows.append(
            {
                "view": "tier",
                "segment": tier,
                "retained_fraction": float(mask.mean()),
                "mean_predicted_abs_log_error": mean_score,
                "mean_absolute_log_error": mean_error,
                **metrics.as_row(),
            }
        )
    order = np.argsort(score, kind="stable")
    for retained in (0.25, 0.50, 0.75, 0.90, 1.0):
        n = max(1, int(np.ceil(len(order) * retained)))
        mask = order[:n]
        metrics = evaluate_estimates(np.exp(point_log[mask]), np.exp(actual_log[mask]))
        rows.append(
            {
                "view": "risk_coverage",
                "segment": f"retain_{retained:.2f}",
                "retained_fraction": retained,
                "mean_predicted_abs_log_error": float(score[mask].mean()),
                "mean_absolute_log_error": float(abs_error[mask].mean()),
                **metrics.as_row(),
            }
        )
    return pl.DataFrame(rows)


def fit_risk_model(
    run_dir: Path, data_dir: Path | None = None, *, seed: int = 42
) -> RiskModelResult:
    """Fit, audit, and persist a risk model alongside a baseline run."""
    fit, val, test = split_frames(run_dir, data_dir)
    del fit  # split provenance matters; the risk learner never sees it
    if val.height < MIN_RISK_VALIDATION_ROWS or test.height < MIN_RISK_TEST_ROWS:
        rejected_metadata: dict[str, object] = {
            "promoted": False,
            "features": list(RISK_FEATURE_NAMES),
            "fit_rows": 0,
            "threshold_rows": 0,
            "test_rows": test.height,
            "rejection_reason": (
                "insufficient support for independent risk fitting, "
                "threshold calibration, and promotion audit"
            ),
            "minimum_validation_rows": MIN_RISK_VALIDATION_ROWS,
            "minimum_test_rows": MIN_RISK_TEST_ROWS,
        }
        evaluation = pl.DataFrame(schema={"view": pl.String, "segment": pl.String, "n": pl.Int64})
        (run_dir / RISK_METADATA_FILE).write_text(json.dumps(rejected_metadata, indent=2) + "\n")
        evaluation.write_parquet(run_dir / RISK_EVALUATION_FILE)
        logger.info(
            "risk model skipped: validation/test support %d/%d below %d/%d",
            val.height,
            test.height,
            MIN_RISK_VALIDATION_ROWS,
            MIN_RISK_TEST_ROWS,
        )
        return RiskModelResult(run_dir, False, rejected_metadata, evaluation)
    cut = max(1, int(val.height * 0.8))
    risk_fit, risk_cal = val.head(cut), val.tail(val.height - cut)
    x_fit, x_cal, x_test = (_risk_matrix(run_dir, frame) for frame in (risk_fit, risk_cal, test))
    y_fit = np.abs(_reference_log_price(run_dir, risk_fit) - _point_log(run_dir, risk_fit))
    y_cal = np.abs(_reference_log_price(run_dir, risk_cal) - _point_log(run_dir, risk_cal))
    model = lgb.train(
        {
            "objective": "regression_l1",
            "metric": "l1",
            "learning_rate": 0.03,
            "num_leaves": 31,
            "min_data_in_leaf": 100,
            "feature_fraction": 0.9,
            "lambda_l2": 2.0,
            "verbose": -1,
            "seed": seed,
        },
        lgb.Dataset(x_fit, label=y_fit, feature_name=list(RISK_FEATURE_NAMES)),
        num_boost_round=1_000,
        valid_sets=[lgb.Dataset(x_cal, label=y_cal, reference=None)],
        callbacks=[lgb.early_stopping(75, verbose=False)],
    )
    cal_score = np.maximum(np.asarray(model.predict(x_cal)), 0.0)
    elevated, high = (float(value) for value in np.quantile(cal_score, [0.75, 0.90]))
    test_score = np.maximum(np.asarray(model.predict(x_test)), 0.0)
    actual_log = _reference_log_price(run_dir, test)
    point_log = _point_log(run_dir, test)
    evaluation = _risk_evaluation(test_score, actual_log, point_log, elevated, high)

    tier = evaluation.filter(pl.col("view") == "tier")
    by_tier = {row["segment"]: row for row in tier.to_dicts()}
    from scipy.stats import spearmanr

    raw_correlation = float(spearmanr(test_score, np.abs(actual_log - point_log)).statistic)
    correlation = raw_correlation if np.isfinite(raw_correlation) else 0.0

    def metric(tier_name: str, name: str) -> float:
        value = by_tier.get(tier_name, {}).get(name)
        return float(value) if value is not None and np.isfinite(float(value)) else np.nan

    standard_rmse = metric("standard", "rmse_log")
    high_rmse = metric("high", "rmse_log")
    standard_mae = metric("standard", "mean_absolute_log_error")
    elevated_mae = metric("elevated", "mean_absolute_log_error")
    high_mae = metric("high", "mean_absolute_log_error")
    promoted = bool(
        np.all(np.isfinite([standard_rmse, high_rmse, standard_mae, elevated_mae, high_mae]))
        and correlation >= 0.10
        and standard_mae < elevated_mae < high_mae
        and high_rmse >= standard_rmse * 1.20
    )
    metadata: dict[str, object] = {
        "promoted": promoted,
        "features": list(RISK_FEATURE_NAMES),
        "prohibited_features": [
            "sale_price_at_scoring",
            "opa_market_value",
            "owner_identity",
            "demographics",
        ],
        "fit_rows": risk_fit.height,
        "threshold_rows": risk_cal.height,
        "test_rows": test.height,
        "best_iteration": model.best_iteration,
        "elevated_threshold": elevated,
        "high_threshold": high,
        "test_spearman": correlation,
        "promotion_rule": ("spearman>=0.10; monotone tier MAE; high-tier RMSE>=1.20x standard"),
    }
    model.save_model(run_dir / RISK_MODEL_FILE)
    (run_dir / RISK_METADATA_FILE).write_text(json.dumps(metadata, indent=2) + "\n")
    evaluation.write_parquet(run_dir / RISK_EVALUATION_FILE)
    logger.info(
        "risk model %s (spearman %.3f)", "promoted" if promoted else "rejected", correlation
    )
    return RiskModelResult(run_dir, promoted, metadata, evaluation)


def score_prediction_risk(
    run_dir: Path, frame: pl.DataFrame
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.str_]]:
    """Return expected absolute-log-error score and calibrated risk tier.

    Runs without a promoted risk artifact degrade safely to a standard tier.
    """
    metadata_path = run_dir / RISK_METADATA_FILE
    model_path = run_dir / RISK_MODEL_FILE
    if not metadata_path.exists() or not model_path.exists():
        return np.zeros(frame.height), np.full(frame.height, "standard")
    metadata = json.loads(metadata_path.read_text())
    if not metadata.get("promoted"):
        return np.zeros(frame.height), np.full(frame.height, "standard")
    model = lgb.Booster(model_file=str(model_path))
    score = np.maximum(np.asarray(model.predict(_risk_matrix(run_dir, frame))), 0.0)
    tier = _tiers(
        score,
        float(metadata["elevated_threshold"]),
        float(metadata["high_threshold"]),
    )
    return score, tier
