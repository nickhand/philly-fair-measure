"""Out-of-time promotion gate for valuation feature challengers.

Feature engineering is cheap; false confidence in a civic model is not.  This
module fits the incumbent and each challenger on the identical time split,
seed, target, recency weights, and financed-market calibration.  It then
scores accuracy, uniformity, vertical equity, high-risk cohorts, and every
sufficiently large district before recommending promotion.

The fast gate uses LightGBM only.  A passing feature family still needs the
full LightGBM/CatBoost/Bayesian retrain and interval audit before production.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.features.characteristic_quality import QUALITY_COLUMNS
from philly_fair_measure.features.property_state import (
    ENTITY_NUMERIC_FEATURES,
    ENTITY_STATE_CATEGORICAL_FEATURES,
    ENTITY_STATE_NUMERIC_FEATURES,
    PROPERTY_STATE_CATEGORICAL_FEATURES,
    PROPERTY_STATE_NUMERIC_FEATURES,
)
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef, read_derived_manifest
from philly_fair_measure.models.baseline import (
    DEFAULT_LGB_PARAMS,
    NUMERIC_FEATURES,
    RECENCY_HALF_LIFE_YEARS,
    _encode,
    _fit_category_mappings,
    _load_frame,
    apply_vertical_calibration,
    feature_lists,
    fit_vertical_calibration,
)
from philly_fair_measure.models.metrics import evaluate_estimates, vertical_equity_indicator

logger = logging.getLogger(__name__)

MEASUREMENT_FEATURES: Final = tuple(
    column
    for column in QUALITY_COLUMNS
    if column
    not in {
        "quality_area_reference_low_90",
        "quality_area_reference_high_90",
    }
)

CHALLENGERS: Final = {
    "measurement": (MEASUREMENT_FEATURES, ()),
    "entity": (ENTITY_NUMERIC_FEATURES, ()),
    "state": (PROPERTY_STATE_NUMERIC_FEATURES, PROPERTY_STATE_CATEGORICAL_FEATURES),
    "measurement_entity": ((*MEASUREMENT_FEATURES, *ENTITY_NUMERIC_FEATURES), ()),
    "measurement_state": (
        (*MEASUREMENT_FEATURES, *PROPERTY_STATE_NUMERIC_FEATURES),
        PROPERTY_STATE_CATEGORICAL_FEATURES,
    ),
    "combined": (
        (*MEASUREMENT_FEATURES, *ENTITY_STATE_NUMERIC_FEATURES),
        ENTITY_STATE_CATEGORICAL_FEATURES,
    ),
}

MIN_DISTRICT_ROWS: Final = 150


@dataclass(frozen=True)
class ChallengerDecision:
    challenger: str
    promote_to_full_retrain: bool
    hard_gates_passed: bool
    material_benefit: bool
    failed_gates: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class ChallengerResult:
    metrics: pl.DataFrame
    decisions: tuple[ChallengerDecision, ...]
    metrics_path: Path
    decisions_path: Path


def _target(frame: pl.DataFrame) -> np.ndarray:
    return np.asarray(
        np.log(frame["sale_price"].to_numpy())
        + frame["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy(),
        dtype=np.float64,
    )


def _fit_challenger(
    fit: pl.DataFrame,
    val: pl.DataFrame,
    test: pl.DataFrame,
    numeric: list[str],
    categorical: list[str],
    *,
    seed: int,
) -> tuple[np.ndarray, int]:
    mappings = _fit_category_mappings(fit, categorical)
    x_fit = _encode(fit, mappings, numeric, categorical)
    x_val = _encode(val, mappings, numeric, categorical)
    x_test = _encode(test, mappings, numeric, categorical)
    y_fit, y_val = _target(fit), _target(val)
    age_days = fit.select(
        (pl.col("sale_date").max() - pl.col("sale_date")).dt.total_days().alias("age")
    )["age"].to_numpy()
    weight = np.power(0.5, age_days / (RECENCY_HALF_LIFE_YEARS * 365.25))
    train = lgb.Dataset(
        x_fit,
        label=y_fit,
        weight=weight,
        feature_name=numeric + categorical,
        categorical_feature=categorical,
    )
    model = lgb.train(
        {**DEFAULT_LGB_PARAMS, "seed": seed},
        train,
        num_boost_round=5_000,
        valid_sets=[train.create_valid(x_val, label=y_val)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    val_log = np.asarray(model.predict(x_val, num_iteration=model.best_iteration))
    test_log = np.asarray(model.predict(x_test, num_iteration=model.best_iteration))
    financed = (val["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()
    calibration_rows = financed if int(financed.sum()) >= 200 else np.ones(val.height, dtype=bool)
    calibration = fit_vertical_calibration(val_log[calibration_rows], y_val[calibration_rows])
    test_log = apply_vertical_calibration(test_log, calibration)
    pred = np.exp(test_log - test["time_adj_log"].fill_null(0.0).to_numpy())
    return np.asarray(pred, dtype=np.float64), int(model.best_iteration)


def _segment_masks(test: pl.DataFrame) -> list[tuple[str, str, np.ndarray]]:
    price = test["sale_price"].to_numpy()
    quintile = np.digitize(price, np.quantile(price, [0.2, 0.4, 0.6, 0.8])) + 1
    masks: list[tuple[str, str, np.ndarray]] = [
        ("overall", "all", np.ones(test.height, dtype=bool)),
        ("finance", "financed", (test["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()),
        ("finance", "cash", (test["fin_cash_sale"].fill_null(0.0) > 0.0).to_numpy()),
        ("price_quintile", "q1", quintile == 1),
        ("price_quintile", "q5", quintile == 5),
    ]
    optional = {
        "characteristic_outlier": "quality_characteristic_outlier",
        "area_outlier": "quality_area_outlier",
        "zero_bed_bath_conflict": "quality_zero_bed_bath_conflict",
        "active_work": "state_active_work_evidence",
        "distress": "state_distress_evidence",
        "multi_account": "entity_multi_account",
    }
    for label, column in optional.items():
        if column not in test.columns:
            continue
        if test.schema[column] == pl.Boolean:
            mask = test[column].fill_null(False).to_numpy()
        else:
            threshold = 0.5 if column.startswith("state_") else 0.0
            mask = (test[column].cast(pl.Float64).fill_null(0.0) > threshold).to_numpy()
        masks.append(("risk_cohort", label, mask))
    if "loc_district" in test.columns:
        district = test["loc_district"].cast(pl.String).fill_null("unknown")
        for label in district.unique().sort().to_list():
            mask = (district == label).to_numpy()
            if int(mask.sum()) >= MIN_DISTRICT_ROWS:
                masks.append(("district", str(label), mask))
    return masks


def _evaluate(
    predictions: dict[str, np.ndarray], test: pl.DataFrame, iterations: dict[str, int]
) -> pl.DataFrame:
    actual = test["sale_price"].to_numpy()
    rows: list[dict[str, object]] = []
    for challenger, estimate in predictions.items():
        for segment_type, segment, mask in _segment_masks(test):
            if int(mask.sum()) < 3:
                continue
            metrics = evaluate_estimates(estimate[mask], actual[mask])
            vei = vertical_equity_indicator(estimate[mask], actual[mask])
            rows.append(
                {
                    "challenger": challenger,
                    "segment_type": segment_type,
                    "segment": segment,
                    "best_iteration": iterations[challenger],
                    **metrics.as_row(),
                    "vei": vei.vei,
                    "vei_verdict": vei.verdict,
                }
            )
    table = pl.DataFrame(rows)
    baseline = table.filter(pl.col("challenger") == "incumbent").select(
        "segment_type",
        "segment",
        pl.col("rmse_log").alias("base_rmse_log"),
        pl.col("cod").alias("base_cod"),
        pl.col("prb").alias("base_prb"),
        pl.col("vei").alias("base_vei"),
    )
    return table.join(baseline, on=["segment_type", "segment"], how="left").with_columns(
        (pl.col("rmse_log") - pl.col("base_rmse_log")).alias("delta_rmse_log"),
        (pl.col("cod") - pl.col("base_cod")).alias("delta_cod"),
        (pl.col("prb").abs() - pl.col("base_prb").abs()).alias("delta_abs_prb"),
        (pl.col("vei").abs() - pl.col("base_vei").abs()).alias("delta_abs_vei"),
    )


def _metric(
    table: pl.DataFrame, challenger: str, segment_type: str, segment: str, name: str
) -> float:
    value = table.filter(
        (pl.col("challenger") == challenger)
        & (pl.col("segment_type") == segment_type)
        & (pl.col("segment") == segment)
    )[name]
    return float(value[0]) if len(value) and value[0] is not None else float("nan")


def _decisions(table: pl.DataFrame) -> tuple[ChallengerDecision, ...]:
    decisions: list[ChallengerDecision] = []
    for challenger in CHALLENGERS:
        failed: list[str] = []
        # Non-inferiority limits are deliberately small relative to run-to-run
        # noise.  Fairness uses absolute PRB/VEI so improving a signed metric by
        # crossing zero cannot be mistaken for deterioration.
        checks = {
            "overall_rmse": _metric(table, challenger, "overall", "all", "delta_rmse_log") <= 0.002,
            "financed_rmse": _metric(table, challenger, "finance", "financed", "delta_rmse_log")
            <= 0.002,
            "q1_rmse": _metric(table, challenger, "price_quintile", "q1", "delta_rmse_log")
            <= 0.005,
            "overall_prb": _metric(table, challenger, "overall", "all", "delta_abs_prb") <= 0.005,
            "overall_vei": _metric(table, challenger, "overall", "all", "delta_abs_vei") <= 1.0,
        }
        # A feature intended to solve exceptional records cannot buy a small
        # citywide win by making a prespecified risk cohort materially worse.
        for cohort in (
            "characteristic_outlier",
            "zero_bed_bath_conflict",
            "active_work",
            "distress",
        ):
            delta = _metric(table, challenger, "risk_cohort", cohort, "delta_rmse_log")
            if not np.isfinite(delta) or delta > 0.003:
                checks[f"{cohort}_rmse"] = False
        candidate_district = table.filter(
            (pl.col("challenger") == challenger) & (pl.col("segment_type") == "district")
        )
        district_delta = candidate_district["delta_rmse_log"].max()
        if (
            candidate_district.height
            and isinstance(district_delta, int | float)
            and district_delta > 0.01
        ):
            checks["worst_district_rmse"] = False
        for name, passed in checks.items():
            if not passed:
                failed.append(name)

        improvements = [
            -_metric(table, challenger, "overall", "all", "delta_rmse_log") >= 0.001,
            -_metric(table, challenger, "finance", "financed", "delta_rmse_log") >= 0.001,
            -_metric(table, challenger, "price_quintile", "q1", "delta_rmse_log") >= 0.002,
        ]
        for cohort in ("characteristic_outlier", "active_work", "distress"):
            delta = _metric(table, challenger, "risk_cohort", cohort, "delta_rmse_log")
            cohort_n = _metric(table, challenger, "risk_cohort", cohort, "n")
            improvements.append(np.isfinite(delta) and cohort_n >= 200 and -delta >= 0.003)
        hard = not failed
        benefit = any(improvements)
        decisions.append(
            ChallengerDecision(
                challenger=challenger,
                promote_to_full_retrain=hard and benefit,
                hard_gates_passed=hard,
                material_benefit=benefit,
                failed_gates=tuple(failed),
                notes=(
                    "Fast LightGBM gate only; a promotion requires the full stack, Bayesian, "
                    "coverage, full-roll, and protected-group diagnostic audits."
                ),
            )
        )
    return tuple(decisions)


def model_challenger_check(data_dir: Path | None = None, *, seed: int = 42) -> ChallengerResult:
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "sale_features.parquet"
    frame = _load_frame(mart_path)
    required = set(MEASUREMENT_FEATURES) | set(ENTITY_STATE_NUMERIC_FEATURES)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "sale feature mart predates challenger features; run "
            f"`fair-measure build-features` first (missing {missing})"
        )

    n_test = max(1, int(frame.height * 0.1))
    train, test = frame.head(frame.height - n_test), frame.tail(n_test)
    n_val = max(1, int(train.height * 0.1))
    fit, val = train.head(train.height - n_val), train.tail(n_val)
    base_numeric, base_categorical = feature_lists(time_adjusted=True)

    predictions: dict[str, np.ndarray] = {}
    iterations: dict[str, int] = {}
    predictions["incumbent"], iterations["incumbent"] = _fit_challenger(
        fit, val, test, base_numeric, base_categorical, seed=seed
    )
    for challenger, (numeric_extra, categorical_extra) in CHALLENGERS.items():
        numeric = [*base_numeric, *[c for c in numeric_extra if c not in NUMERIC_FEATURES]]
        categorical = [*base_categorical, *categorical_extra]
        predictions[challenger], iterations[challenger] = _fit_challenger(
            fit, val, test, numeric, categorical, seed=seed
        )
        logger.info("challenger %s fit at iteration %d", challenger, iterations[challenger])

    metrics = _evaluate(predictions, test, iterations)
    decisions = _decisions(metrics)
    mart_manifest = read_derived_manifest(mart_path)
    metrics_path, _ = write_derived_table(
        metrics,
        root,
        "diagnostics",
        "model_challengers",
        [
            InputRef(
                dataset=f"{mart_manifest.layer}/{mart_manifest.table}",
                fetched_at=mart_manifest.built_at.isoformat(),
            )
        ],
        notes="same-split LightGBM promotion gate; production requires full retrain audit",
    )
    decisions_path = metrics_path.with_name("model_challengers.decisions.json")
    decisions_path.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).isoformat(),
                "policy": {
                    "hard_non_inferiority": {
                        "overall_rmse_log": 0.002,
                        "financed_rmse_log": 0.002,
                        "q1_rmse_log": 0.005,
                        "overall_abs_prb": 0.005,
                        "overall_abs_vei": 1.0,
                        "any_district_rmse_log": 0.01,
                        "prespecified_risk_cohort_rmse_log": 0.003,
                    },
                    "material_benefit": (
                        "at least one prespecified overall/financed/q1/risk-cohort improvement"
                    ),
                },
                "decisions": [asdict(item) for item in decisions],
            },
            indent=2,
        )
        + "\n"
    )
    return ChallengerResult(metrics, decisions, metrics_path, decisions_path)
