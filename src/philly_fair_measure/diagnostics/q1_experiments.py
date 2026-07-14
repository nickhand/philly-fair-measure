"""Label-free experiments for the low-value (Q1) error tail.

The bottom sale-price quintile is not one market.  It mixes ordinary financed
homes, wholesale/cash transactions, shells, and properties changing state.
This module tests four ways to separate those mechanisms without manual
labels, using the production out-of-time split and the same accuracy/fairness
metrics as the model challenger gate:

* ``channel_decomposition`` estimates cash-channel residual gaps from stable
  homes on an inner holdout, shrinks them by predicted-value tier, lifts only
  stable cash training targets, and outputs channel-neutral value.
* ``repeat_recovery`` weakly labels likely condition changes from large,
  time-adjusted repeat-sale recoveries confirmed before validation begins.  A
  classifier may use only information available as of the first sale.
* ``low_value_specialist`` trains a specialist on homes routed by the
  incumbent's own preliminary prediction and blends smoothly at the boundary.
* ``segment_calibration`` learns monotone, smoothed corrections by predicted-
  value segment from financed validation residuals.

Future repeat sales are labels for old training examples, never scoring
features.  Sale price and cash status are never valuation inputs at scoring.
Every candidate remains an experiment until it clears the untouched test-set
gates; rejected results are still persisted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef, read_derived_manifest
from philly_fair_measure.models.baseline import (
    DEFAULT_LGB_PARAMS,
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

RECOVERY_MIN_DAYS: Final = 120
RECOVERY_MAX_DAYS: Final = 1_095
RECOVERY_POSITIVE_GAIN: Final = float(np.log(1.60))
RECOVERY_STABLE_GAIN: Final = float(np.log(1.20))
MAX_CHANNEL_DISCOUNT_LOG: Final = float(-np.log(1.50))


@dataclass(frozen=True)
class Q1Decision:
    challenger: str
    promote_to_full_retrain: bool
    hard_gates_passed: bool
    material_q1_benefit: bool
    failed_gates: tuple[str, ...]


@dataclass(frozen=True)
class Q1ExperimentResult:
    metrics: pl.DataFrame
    decisions: tuple[Q1Decision, ...]
    diagnostics: dict[str, object]
    metrics_path: Path
    decisions_path: Path


@dataclass(frozen=True)
class _ValueFit:
    model: lgb.Booster
    predictions: dict[str, np.ndarray]
    best_iteration: int


def _target(frame: pl.DataFrame) -> np.ndarray:
    return np.asarray(
        np.log(frame["sale_price"].to_numpy())
        + frame["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy(),
        dtype=np.float64,
    )


def _fit_value_model(
    fit: pl.DataFrame,
    val: pl.DataFrame,
    predict_frames: dict[str, pl.DataFrame],
    numeric: list[str],
    categorical: list[str],
    *,
    target_fit: np.ndarray | None = None,
    target_val: np.ndarray | None = None,
    fit_mask: np.ndarray | None = None,
    val_mask: np.ndarray | None = None,
    seed: int = 42,
) -> _ValueFit:
    fit_mask = np.ones(fit.height, dtype=bool) if fit_mask is None else fit_mask
    val_mask = np.ones(val.height, dtype=bool) if val_mask is None else val_mask
    fit_used = fit.filter(pl.Series(fit_mask))
    val_used = val.filter(pl.Series(val_mask))
    y_fit = _target(fit) if target_fit is None else target_fit
    y_val = _target(val) if target_val is None else target_val
    y_fit, y_val = y_fit[fit_mask], y_val[val_mask]
    mappings = _fit_category_mappings(fit_used, categorical)
    x_fit = _encode(fit_used, mappings, numeric, categorical)
    x_val = _encode(val_used, mappings, numeric, categorical)
    age_days = fit_used.select(
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
    predictions = {
        name: np.asarray(
            model.predict(
                _encode(frame, mappings, numeric, categorical), num_iteration=model.best_iteration
            ),
            dtype=np.float64,
        )
        for name, frame in predict_frames.items()
    }
    return _ValueFit(model, predictions, int(model.best_iteration))


def repeat_recovery_labels(frame: pl.DataFrame, confirmation_cutoff: date) -> pl.DataFrame:
    """Weak labels whose confirming resale was observable before validation.

    A 60%+ reference-frame recovery within 4--36 months is a positive likely
    state-change label.  A repeat within 20% is a stable negative.  Ambiguous
    pairs are excluded; the downstream classifier never sees either price.
    """
    next_expressions = [
        pl.col("sale_date").shift(-1).over("parcel_id").alias("next_sale_date"),
        pl.col("sale_price").shift(-1).over("parcel_id").alias("next_sale_price"),
        pl.col("time_adj_log").shift(-1).over("parcel_id").alias("next_time_adj_log"),
    ]
    renovation_columns = [
        name
        for name in (
            "evt_n_completed_reno_permits_5y_before",
            "evt_n_reno_permits_5y_before",
            "state_completed_reno_evidence",
        )
        if name in frame.columns
    ]
    next_expressions.extend(
        pl.col(name).shift(-1).over("parcel_id").alias(f"next_{name}")
        for name in renovation_columns
    )
    ordered = frame.sort("parcel_id", "sale_date", "sale_id").with_columns(next_expressions)
    days = (pl.col("next_sale_date") - pl.col("sale_date")).dt.total_days()
    gain = (
        pl.col("next_sale_price").log()
        + pl.col("next_time_adj_log")
        - pl.col("sale_price").log()
        - pl.col("time_adj_log")
    )
    renovation_evidence = (
        pl.any_horizontal(
            [
                pl.col(f"next_{name}").cast(pl.Float64).fill_null(0.0)
                > pl.col(name).cast(pl.Float64).fill_null(0.0) + 0.05
                for name in renovation_columns
            ]
        )
        if renovation_columns
        else pl.lit(False)
    )
    return (
        ordered.with_columns(days.alias("recovery_days"), gain.alias("recovery_log_gain"))
        .filter(
            pl.col("next_sale_date").is_not_null()
            & (pl.col("next_sale_date") < pl.lit(confirmation_cutoff))
            & pl.col("recovery_days").is_between(RECOVERY_MIN_DAYS, RECOVERY_MAX_DAYS)
        )
        .with_columns(renovation_evidence.alias("recovery_renovation_evidence"))
        .with_columns(
            pl.when(
                (pl.col("recovery_log_gain") >= RECOVERY_POSITIVE_GAIN)
                & pl.col("recovery_renovation_evidence")
            )
            .then(pl.lit(1))
            .when(pl.col("recovery_log_gain").abs() <= RECOVERY_STABLE_GAIN)
            .then(pl.lit(0))
            .otherwise(None)
            .cast(pl.Int8)
            .alias("weak_recovery_label")
        )
        .filter(pl.col("weak_recovery_label").is_not_null())
        .select(
            "sale_id",
            "weak_recovery_label",
            "recovery_days",
            "recovery_log_gain",
            "recovery_renovation_evidence",
            "next_sale_date",
        )
    )


def _fit_recovery_probability(
    fit: pl.DataFrame,
    val: pl.DataFrame,
    test: pl.DataFrame,
    numeric: list[str],
    categorical: list[str],
    *,
    seed: int,
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    confirmation_cutoff = val["sale_date"].min()
    if not isinstance(confirmation_cutoff, date):
        raise ValueError("validation slice has no usable sale-date cutoff")
    labels = repeat_recovery_labels(
        pl.concat([fit, val, test], how="vertical_relaxed"),
        confirmation_cutoff=confirmation_cutoff,
    )
    labeled = fit.join(labels.select("sale_id", "weak_recovery_label"), on="sale_id", how="inner")
    positives = int(labeled["weak_recovery_label"].sum()) if labeled.height else 0
    negatives = labeled.height - positives
    diagnostics: dict[str, object] = {
        "weak_label_rows": labeled.height,
        "weak_positive_rows": positives,
        "weak_negative_rows": negatives,
        "confirmation_cutoff": str(val["sale_date"].min()),
    }
    if positives < 100 or negatives < 200:
        diagnostics["weak_label_status"] = "insufficient_support"
        return {
            "fit": np.zeros(fit.height),
            "val": np.zeros(val.height),
            "test": np.zeros(test.height),
        }, diagnostics

    cut = max(1, int(labeled.height * 0.8))
    train, hold = labeled.head(cut), labeled.tail(labeled.height - cut)
    mappings = _fit_category_mappings(train, categorical)
    x_train = _encode(train, mappings, numeric, categorical)
    x_hold = _encode(hold, mappings, numeric, categorical)
    scale_pos = max(1.0, negatives / positives)
    model = lgb.train(
        {
            **DEFAULT_LGB_PARAMS,
            "objective": "binary",
            "metric": "binary_logloss",
            "num_leaves": 63,
            "min_data_in_leaf": 50,
            "scale_pos_weight": scale_pos,
            "seed": seed,
        },
        lgb.Dataset(
            x_train,
            label=train["weak_recovery_label"].to_numpy(),
            feature_name=numeric + categorical,
            categorical_feature=categorical,
        ),
        num_boost_round=2_000,
        valid_sets=[lgb.Dataset(x_hold, label=hold["weak_recovery_label"].to_numpy())],
        callbacks=[lgb.early_stopping(75, verbose=False)],
    )
    probability = {
        name: np.asarray(
            model.predict(
                _encode(frame, mappings, numeric, categorical), num_iteration=model.best_iteration
            ),
            dtype=np.float64,
        )
        for name, frame in {"fit": fit, "val": val, "test": test}.items()
    }
    diagnostics.update(
        {
            "weak_label_status": "trained",
            "weak_classifier_iteration": int(model.best_iteration),
            "weak_probability_mean_test": float(probability["test"].mean()),
        }
    )
    return probability, diagnostics


def _instability(frame: pl.DataFrame) -> np.ndarray:
    values = []
    for name in (
        "state_distress_evidence",
        "state_active_work_evidence",
        "state_transition_evidence",
        "state_competing_evidence",
    ):
        values.append(frame[name].cast(pl.Float64).fill_null(0.0).to_numpy())
    state = np.maximum.reduce(values)
    if "quality_characteristic_outlier" in frame.columns:
        outlier = frame["quality_characteristic_outlier"].fill_null(False).to_numpy()
        state = np.maximum(state, outlier.astype(float) * 0.75)
    return np.clip(np.asarray(state, dtype=np.float64), 0.0, 1.0)


def _fit_channel_delta(
    inner_fit: pl.DataFrame,
    inner_hold: pl.DataFrame,
    frames: dict[str, pl.DataFrame],
    base_predictions: dict[str, np.ndarray],
    numeric: list[str],
    categorical: list[str],
    *,
    seed: int,
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    provisional = _fit_value_model(
        inner_fit,
        inner_hold,
        {"hold": inner_hold},
        numeric,
        categorical,
        seed=seed,
    )
    residual = _target(inner_hold) - provisional.predictions["hold"]
    cash = inner_hold["fin_cash_sale"].cast(pl.Float64).fill_null(1.0).to_numpy() > 0.0
    instability = _instability(inner_hold)
    stable = instability < 0.25
    base_hold = provisional.predictions["hold"]
    edges = np.quantile(base_hold, [0.2, 0.4, 0.6, 0.8])
    hold_bin = np.digitize(base_hold, edges)

    def residual_gap(mask: np.ndarray) -> tuple[float, int, int]:
        cash_values = residual[mask & cash]
        financed_values = residual[mask & ~cash]
        if not len(cash_values) or not len(financed_values):
            return 0.0, len(cash_values), len(financed_values)
        gap = float(np.median(cash_values) - np.median(financed_values))
        return (
            float(np.clip(min(gap, 0.0), MAX_CHANNEL_DISCOUNT_LOG, 0.0)),
            len(cash_values),
            len(financed_values),
        )

    global_gap, global_cash_n, global_financed_n = residual_gap(stable)
    gaps: list[float] = []
    gap_rows: list[dict[str, object]] = []
    for value_bin in range(5):
        gap, cash_n, financed_n = residual_gap(stable & (hold_bin == value_bin))
        support = min(cash_n, financed_n)
        shrink = support / (support + 500.0)
        gap = float(shrink * gap + (1.0 - shrink) * global_gap)
        gaps.append(gap)
        gap_rows.append(
            {
                "predicted_value_quintile": value_bin + 1,
                "cash_rows": cash_n,
                "financed_rows": financed_n,
                "discount_pct": float(np.expm1(gap)),
            }
        )

    deltas: dict[str, np.ndarray] = {}
    for name, frame in frames.items():
        value_bin = np.digitize(base_predictions[name], edges)
        # A channel correction is strongest for stable homes.  For a shell or
        # active conversion, the low cash price is likely physical state, not
        # a wholesale nuisance to erase.  Squaring makes this conservative.
        stable_weight = np.square(1.0 - _instability(frame))
        deltas[name] = np.asarray(np.array(gaps)[value_bin] * stable_weight, dtype=np.float64)
    test_distress = (
        frames["test"]["state_distress_evidence"].cast(pl.Float64).fill_null(0.0).to_numpy()
    )
    diagnostics: dict[str, object] = {
        "channel_method": "stable-home residual gaps by predicted-value quintile",
        "channel_inner_hold_rows": inner_hold.height,
        "channel_stable_hold_rows": int(stable.sum()),
        "channel_stable_cash_rows": global_cash_n,
        "channel_stable_financed_rows": global_financed_n,
        "channel_discount_curve": gap_rows,
        "channel_discount_median": float(np.expm1(np.median(deltas["test"]))),
        "channel_discount_clean_median": float(
            np.expm1(np.median(deltas["test"][test_distress < 0.5]))
        ),
        "channel_discount_distress_median": float(
            np.expm1(np.median(deltas["test"][test_distress >= 0.5]))
        )
        if np.any(test_distress >= 0.5)
        else None,
    }
    return deltas, diagnostics


def smooth_low_value_weight(base_log: np.ndarray, center: float, scale: float) -> np.ndarray:
    """Stable, monotone routing weight for the low-value expert."""
    z = np.clip((np.asarray(base_log) - center) / max(scale, 1e-6), -30.0, 30.0)
    return np.asarray(1.0 / (1.0 + np.exp(z)), dtype=np.float64)


def _calibrate(
    val_log: np.ndarray, test_log: np.ndarray, val: pl.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    financed = (val["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()
    mask = financed if int(financed.sum()) >= 200 else np.ones(val.height, dtype=bool)
    calibration = fit_vertical_calibration(val_log[mask], _target(val)[mask])
    return (
        apply_vertical_calibration(val_log, calibration),
        apply_vertical_calibration(test_log, calibration),
    )


def _smoothed_segment_calibration(
    val_log: np.ndarray, test_log: np.ndarray, val: pl.DataFrame, *, segments: int = 5
) -> tuple[np.ndarray, dict[str, object]]:
    """Robust K-segment residual calibration with monotone interpolation.

    Segment assignment uses the preliminary prediction, which is available at
    inference.  Median residuals are learned on financed validation rows; the
    calibrated knot values are forced monotone before interpolation.
    """
    financed = (val["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()
    pred = np.asarray(val_log[financed], dtype=np.float64)
    actual = _target(val)[financed]
    edges = np.quantile(pred, np.linspace(0.0, 1.0, segments + 1)[1:-1])
    value_bin = np.digitize(pred, edges)
    centers: list[float] = []
    corrected: list[float] = []
    rows: list[dict[str, object]] = []
    for value_segment in range(segments):
        mask = value_bin == value_segment
        center = float(np.median(pred[mask]))
        correction = float(np.median(actual[mask] - pred[mask]))
        centers.append(center)
        corrected.append(center + correction)
        rows.append(
            {
                "segment": value_segment + 1,
                "n": int(mask.sum()),
                "center_log": center,
                "median_correction_log": correction,
            }
        )
    monotone = np.maximum.accumulate(np.asarray(corrected, dtype=np.float64))
    correction_knots = monotone - np.asarray(centers)
    calibrated = np.asarray(
        test_log + np.interp(test_log, centers, correction_knots), dtype=np.float64
    )
    return calibrated, {"segment_calibration": rows}


def _evaluate(
    retail_logs: dict[str, np.ndarray],
    transaction_delta: np.ndarray,
    test: pl.DataFrame,
    iterations: dict[str, int],
) -> pl.DataFrame:
    y_actual = _target(test)
    cash = test["fin_cash_sale"].cast(pl.Float64).fill_null(1.0).to_numpy()
    y_retail = y_actual - cash * transaction_delta
    financed = cash == 0.0
    retail_quintile = np.digitize(y_retail, np.quantile(y_retail, [0.2, 0.4, 0.6, 0.8])) + 1
    financed_q = np.zeros(test.height, dtype=int)
    financed_q[financed] = (
        np.digitize(y_actual[financed], np.quantile(y_actual[financed], [0.2, 0.4, 0.6, 0.8])) + 1
    )
    actual_q = np.digitize(y_actual, np.quantile(y_actual, [0.2, 0.4, 0.6, 0.8])) + 1
    segments: list[tuple[str, str, str, np.ndarray]] = [
        ("retail", "all", "retail", np.ones(test.height, dtype=bool)),
        ("retail", "q1", "retail", retail_quintile == 1),
        ("retail", "q5", "retail", retail_quintile == 5),
        ("financed", "all", "retail", financed),
        ("financed", "q1", "retail", financed & (financed_q == 1)),
        ("financed", "q5", "retail", financed & (financed_q == 5)),
        ("transaction", "all", "transaction", np.ones(test.height, dtype=bool)),
        ("transaction", "q1", "transaction", actual_q == 1),
    ]
    for label, column in {
        "characteristic_outlier": "quality_characteristic_outlier",
        "active_work": "state_active_work_evidence",
        "distress": "state_distress_evidence",
    }.items():
        if column not in test.columns:
            continue
        if test.schema[column] == pl.Boolean:
            mask = test[column].fill_null(False).to_numpy()
        else:
            mask = (test[column].cast(pl.Float64).fill_null(0.0) > 0.5).to_numpy()
        segments.append(("risk", label, "retail", mask))
    district = test["loc_district"].cast(pl.String).fill_null("unknown")
    for label in district.unique().sort().to_list():
        mask = (district == label).to_numpy()
        if int(mask.sum()) >= 150:
            segments.append(("district", str(label), "retail", mask))

    time_adj = test["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    rows: list[dict[str, object]] = []
    for challenger, retail_log in retail_logs.items():
        transaction_log = retail_log + cash * transaction_delta
        for segment_type, segment, convention, mask in segments:
            if int(mask.sum()) < 3:
                continue
            target_log = y_retail if convention == "retail" else y_actual
            prediction_log = retail_log if convention == "retail" else transaction_log
            target = np.exp(target_log[mask] - time_adj[mask])
            prediction = np.exp(prediction_log[mask] - time_adj[mask])
            metrics = evaluate_estimates(prediction, target)
            vei = vertical_equity_indicator(prediction, target)
            rows.append(
                {
                    "challenger": challenger,
                    "segment_type": segment_type,
                    "segment": segment,
                    "target_convention": convention,
                    "best_iteration": iterations[challenger],
                    **metrics.as_row(),
                    "vei": vei.vei,
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


def _decide(table: pl.DataFrame, challengers: list[str]) -> tuple[Q1Decision, ...]:
    decisions: list[Q1Decision] = []
    for challenger in challengers:
        checks = {
            "retail_all_rmse": _metric(table, challenger, "retail", "all", "delta_rmse_log")
            <= 0.002,
            "financed_all_rmse": _metric(table, challenger, "financed", "all", "delta_rmse_log")
            <= 0.002,
            "financed_q5_rmse": _metric(table, challenger, "financed", "q5", "delta_rmse_log")
            <= 0.003,
            "transaction_all_rmse": _metric(
                table, challenger, "transaction", "all", "delta_rmse_log"
            )
            <= 0.002,
            "retail_abs_prb": _metric(table, challenger, "retail", "all", "delta_abs_prb") <= 0.005,
            "retail_abs_vei": _metric(table, challenger, "retail", "all", "delta_abs_vei") <= 1.0,
        }
        for cohort in ("characteristic_outlier", "active_work", "distress"):
            delta = _metric(table, challenger, "risk", cohort, "delta_rmse_log")
            checks[f"{cohort}_rmse"] = np.isfinite(delta) and delta <= 0.003
        district = table.filter(
            (pl.col("challenger") == challenger) & (pl.col("segment_type") == "district")
        )
        district_delta = district["delta_rmse_log"].max() if district.height else None
        checks["worst_district_rmse"] = bool(
            district_delta is None
            or (isinstance(district_delta, int | float) and district_delta <= 0.01)
        )
        failed = tuple(name for name, passed in checks.items() if not passed)
        q1_gain = -_metric(table, challenger, "financed", "q1", "delta_rmse_log")
        retail_q1_gain = -_metric(table, challenger, "retail", "q1", "delta_rmse_log")
        material = bool(max(q1_gain, retail_q1_gain) >= 0.003)
        decisions.append(
            Q1Decision(
                challenger=challenger,
                promote_to_full_retrain=not failed and material,
                hard_gates_passed=not failed,
                material_q1_benefit=material,
                failed_gates=failed,
            )
        )
    return tuple(decisions)


def q1_experiment_check(data_dir: Path | None = None, *, seed: int = 42) -> Q1ExperimentResult:
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "sale_features.parquet"
    frame = _load_frame(mart_path)
    n_test = max(1, int(frame.height * 0.1))
    train, test = frame.head(frame.height - n_test), frame.tail(n_test)
    n_val = max(1, int(train.height * 0.1))
    fit, val = train.head(train.height - n_val), train.tail(n_val)
    numeric, categorical = feature_lists(time_adjusted=True)

    base = _fit_value_model(
        fit,
        val,
        {"fit": fit, "val": val, "test": test},
        numeric,
        categorical,
        seed=seed,
    )
    base_val, base_test = _calibrate(base.predictions["val"], base.predictions["test"], val)

    inner_cut = max(1, int(fit.height * 0.8))
    deltas, channel_diagnostics = _fit_channel_delta(
        fit.head(inner_cut),
        fit.tail(fit.height - inner_cut),
        {"fit": fit, "val": val, "test": test},
        base.predictions,
        numeric,
        categorical,
        seed=seed,
    )
    cash_fit = fit["fin_cash_sale"].cast(pl.Float64).fill_null(1.0).to_numpy()
    retail_target_fit = _target(fit) - cash_fit * deltas["fit"]
    financed_val = (val["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()
    channel = _fit_value_model(
        fit,
        val,
        {"val": val, "test": test},
        numeric,
        categorical,
        target_fit=retail_target_fit,
        val_mask=financed_val,
        seed=seed,
    )
    channel_val, channel_test = _calibrate(
        channel.predictions["val"], channel.predictions["test"], val
    )
    segment_test, segment_diagnostics = _smoothed_segment_calibration(
        channel_val, channel_test, val
    )

    recovery_probability, recovery_diagnostics = _fit_recovery_probability(
        fit, val, test, numeric, categorical, seed=seed
    )
    fit_recovery = fit.with_columns(
        pl.Series("weak_recovery_probability", recovery_probability["fit"])
    )
    val_recovery = val.with_columns(
        pl.Series("weak_recovery_probability", recovery_probability["val"])
    )
    test_recovery = test.with_columns(
        pl.Series("weak_recovery_probability", recovery_probability["test"])
    )
    recovery = _fit_value_model(
        fit_recovery,
        val_recovery,
        {"val": val_recovery, "test": test_recovery},
        [*numeric, "weak_recovery_probability"],
        categorical,
        target_fit=retail_target_fit,
        val_mask=financed_val,
        seed=seed,
    )
    recovery_val, recovery_test = _calibrate(
        recovery.predictions["val"], recovery.predictions["test"], val
    )

    center = float(np.quantile(base.predictions["fit"], 0.35))
    train_ceiling = float(np.quantile(base.predictions["fit"], 0.50))
    q25, q45 = np.quantile(base.predictions["fit"], [0.25, 0.45])
    scale = max(float((q45 - q25) / 2.0), 0.10)
    low_fit_mask = base.predictions["fit"] <= train_ceiling
    low_val_mask = (base.predictions["val"] <= train_ceiling) & financed_val
    low = _fit_value_model(
        fit,
        val,
        {"val": val, "test": test},
        numeric,
        categorical,
        target_fit=retail_target_fit,
        fit_mask=low_fit_mask,
        val_mask=low_val_mask,
        seed=seed,
    )
    val_weight = smooth_low_value_weight(base.predictions["val"], center, scale)
    test_weight = smooth_low_value_weight(base.predictions["test"], center, scale)
    # Validation chooses only the strength of a prespecified smooth router.
    # The test slice remains untouched.
    financed_prices = _target(val)[financed_val]
    financed_q1_edge = np.quantile(financed_prices, 0.20)
    val_q1 = financed_val & (_target(val) <= financed_q1_edge)
    best_alpha, best_objective = 0.0, float("inf")
    best_test = channel.predictions["test"]
    for alpha in (0.25, 0.50, 0.75, 1.0):
        candidate_val_raw = (
            alpha * val_weight * low.predictions["val"]
            + (1.0 - alpha * val_weight) * channel.predictions["val"]
        )
        candidate_test_raw = (
            alpha * test_weight * low.predictions["test"]
            + (1.0 - alpha * test_weight) * channel.predictions["test"]
        )
        candidate_val, candidate_test = _calibrate(candidate_val_raw, candidate_test_raw, val)
        q1_rmse = float(np.sqrt(np.mean((_target(val)[val_q1] - candidate_val[val_q1]) ** 2)))
        overall_rmse = float(
            np.sqrt(np.mean((_target(val)[financed_val] - candidate_val[financed_val]) ** 2))
        )
        channel_overall = float(
            np.sqrt(np.mean((_target(val)[financed_val] - channel_val[financed_val]) ** 2))
        )
        if overall_rmse <= channel_overall + 0.001 and q1_rmse < best_objective:
            best_alpha, best_objective = alpha, q1_rmse
            best_test = candidate_test

    retail_logs = {
        "incumbent": base_test,
        "channel_decomposition": channel_test,
        "segment_calibration": segment_test,
        "repeat_recovery": recovery_test,
        "low_value_specialist": best_test,
    }
    iterations = {
        "incumbent": base.best_iteration,
        "channel_decomposition": channel.best_iteration,
        "segment_calibration": channel.best_iteration,
        "repeat_recovery": recovery.best_iteration,
        "low_value_specialist": low.best_iteration,
    }
    metrics = _evaluate(retail_logs, deltas["test"], test, iterations)
    challengers = [name for name in retail_logs if name != "incumbent"]
    decisions = _decide(metrics, challengers)
    diagnostics: dict[str, object] = {
        **channel_diagnostics,
        **segment_diagnostics,
        **recovery_diagnostics,
        "low_value_center_log": center,
        "low_value_scale_log": scale,
        "low_value_train_rows": int(low_fit_mask.sum()),
        "low_value_alpha": best_alpha,
        "low_value_validation_q1_rmse": best_objective,
        "rows": {"fit": fit.height, "validation": val.height, "test": test.height},
    }
    mart_manifest = read_derived_manifest(mart_path)
    metrics_path, _ = write_derived_table(
        metrics,
        root,
        "diagnostics",
        "q1_experiments",
        [
            InputRef(
                dataset=f"{mart_manifest.layer}/{mart_manifest.table}",
                fetched_at=mart_manifest.built_at.isoformat(),
            )
        ],
        notes="label-free Q1 channel/recovery/specialist/segment out-of-time gate",
    )
    decisions_path = metrics_path.with_name("q1_experiments.decisions.json")
    decisions_path.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).isoformat(),
                "diagnostics": diagnostics,
                "decisions": [asdict(item) for item in decisions],
            },
            indent=2,
        )
        + "\n"
    )
    return Q1ExperimentResult(metrics, decisions, diagnostics, metrics_path, decisions_path)
