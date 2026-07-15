"""Auxiliary, leakage-safe renovation-transition probability model.

The binary target is a large time-adjusted recovery on a historical repeat
sale.  It is a weak supervision signal, not a claim that every positive is a
flip.  Valuation models consume only cross-fitted probabilities and dated
episode evidence; scoring uses a classifier trained on completed historical
episodes and persisted beside the valuation run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure.features.renovation_episodes import EPISODE_RAW_FEATURES

TRANSITION_MODEL_FILE: Final = "renovation_transition_model.txt"
TRANSITION_METADATA_FILE: Final = "renovation_transition_model.json"
TRANSITION_CROSSFIT_FILE: Final = "renovation_transition_crossfit.parquet"
TRANSITION_PROBABILITY_FEATURE: Final = "episode_transition_probability"
_ROW_KEYS: Final = ("sale_id", "parcel_id", "sale_date")

PROBABILITY_INPUTS: Final = (
    *EPISODE_RAW_FEATURES,
    "mkt_parcel_prev_log_price_ref",
    "mkt_knn_price_anchor_log",
    "mkt_knn_n",
    "fin_n_mortgages_5y_before",
    "fin_mtg_days_since",
    "fin_hard_money_5y_before",
    "evt_n_unpermitted_work_complaints_5y_before",
    "evt_n_open_severe_at_sale",
    "state_active_work_evidence",
    "state_distress_evidence",
    "state_completed_reno_evidence",
    "state_measurement_conflict_evidence",
    "state_competing_evidence",
    "quality_characteristic_conflict_score",
    "char_new_build",
)


def _ensure_inputs(frame: pl.DataFrame, inputs: tuple[str, ...]) -> pl.DataFrame:
    missing = [name for name in inputs if name not in frame.columns]
    if not missing:
        return frame
    return frame.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in missing])


def probability_matrix(frame: pl.DataFrame, inputs: tuple[str, ...]) -> np.ndarray:
    ensured = _ensure_inputs(frame, inputs)
    return np.asarray(
        ensured.select(
            *[
                pl.col(name).cast(pl.Float64, strict=False).fill_null(float("nan"))
                for name in inputs
            ]
        ).to_numpy(),
        dtype=np.float64,
    )


@dataclass(frozen=True)
class CalibratedTransitionModel:
    model: lgb.Booster
    calibration_x: npt.NDArray[np.float64]
    calibration_y: npt.NDArray[np.float64]
    best_iteration: int
    training_prior: float
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class TransitionProbabilityResult:
    probabilities: dict[str, npt.NDArray[np.float64]]
    diagnostics: dict[str, object]
    model: CalibratedTransitionModel


def fit_calibrated_transition_model(
    labeled: pl.DataFrame,
    *,
    inputs: tuple[str, ...] = PROBABILITY_INPUTS,
    seed: int,
) -> CalibratedTransitionModel | None:
    """Fit with a later holdout used only for monotone probability calibration."""
    from sklearn.isotonic import IsotonicRegression

    ordered = labeled.sort("sale_date", "sale_id")
    positives = int(ordered["episode_high_recovery_label"].sum())
    negatives = ordered.height - positives
    if positives < 100 or negatives < 100:
        return None
    cut = max(1, int(ordered.height * 0.8))
    train, hold = ordered.head(cut), ordered.tail(ordered.height - cut)
    if hold.height < 100 or hold["episode_high_recovery_label"].n_unique() < 2:
        return None
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.04,
        "num_leaves": 31,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.85,
        "lambda_l2": 2.0,
        "verbose": -1,
        "seed": seed,
    }
    model = lgb.train(
        params,
        lgb.Dataset(
            probability_matrix(train, inputs),
            label=train["episode_high_recovery_label"].to_numpy(),
            feature_name=list(inputs),
        ),
        num_boost_round=1_500,
        valid_sets=[
            lgb.Dataset(
                probability_matrix(hold, inputs),
                label=hold["episode_high_recovery_label"].to_numpy(),
            )
        ],
        callbacks=[lgb.early_stopping(75, verbose=False)],
    )
    best_iteration = max(1, int(model.best_iteration))
    hold_raw = np.asarray(
        model.predict(probability_matrix(hold, inputs), num_iteration=best_iteration),
        dtype=np.float64,
    )
    isotonic = IsotonicRegression(increasing=True, out_of_bounds="clip")
    isotonic.fit(hold_raw, hold["episode_high_recovery_label"].to_numpy())
    final = lgb.train(
        params,
        lgb.Dataset(
            probability_matrix(ordered, inputs),
            label=ordered["episode_high_recovery_label"].to_numpy(),
            feature_name=list(inputs),
        ),
        num_boost_round=best_iteration,
    )
    return CalibratedTransitionModel(
        model=final,
        calibration_x=np.asarray(isotonic.X_thresholds_, dtype=np.float64),
        calibration_y=np.asarray(isotonic.y_thresholds_, dtype=np.float64),
        best_iteration=best_iteration,
        training_prior=positives / ordered.height,
        inputs=inputs,
    )


def predict_transition_probability(
    model: CalibratedTransitionModel, frame: pl.DataFrame
) -> npt.NDArray[np.float64]:
    raw = np.asarray(
        model.model.predict(
            probability_matrix(frame, model.inputs), num_iteration=model.best_iteration
        ),
        dtype=np.float64,
    )
    calibrated = np.interp(raw, model.calibration_x, model.calibration_y)
    if "episode_eligible" in frame.columns:
        eligible = frame["episode_eligible"].cast(pl.Float64).fill_null(0.0).to_numpy()
    else:
        eligible = np.zeros(frame.height, dtype=np.float64)
    return np.asarray(np.clip(calibrated, 0.0, 1.0) * eligible, dtype=np.float64)


def cross_fitted_transition_probability(
    fit: pl.DataFrame,
    val: pl.DataFrame,
    test: pl.DataFrame,
    *,
    folds: int = 5,
    seed: int = 42,
) -> TransitionProbabilityResult:
    """Expanding-time probabilities with no row's own target in its score."""
    fit_probability = np.zeros(fit.height, dtype=np.float64)
    boundaries = np.linspace(0, fit.height, folds + 1, dtype=int)
    fold_rows: list[dict[str, object]] = []
    for fold in range(folds):
        start, stop = int(boundaries[fold]), int(boundaries[fold + 1])
        earlier = fit.head(start).filter(pl.col("episode_high_recovery_label").is_not_null())
        current = fit.slice(start, stop - start)
        classifier = fit_calibrated_transition_model(earlier, seed=seed + fold)
        if classifier is None:
            eligible = current["episode_eligible"].cast(pl.Float64).fill_null(0.0).to_numpy() > 0
            # Missing is honest before enough earlier outcomes exist; a false
            # zero would teach the valuation model that early eligible rows
            # were known non-transitions.
            predicted = np.where(eligible, np.nan, 0.0)
            status = "insufficient_history_missing"
        else:
            predicted = predict_transition_probability(classifier, current)
            status = "trained"
        fit_probability[start:stop] = predicted
        fold_rows.append(
            {
                "fold": fold + 1,
                "prediction_rows": current.height,
                "label_rows_before_fold": earlier.height,
                "status": status,
            }
        )

    labeled_fit = fit.filter(pl.col("episode_high_recovery_label").is_not_null())
    final = fit_calibrated_transition_model(labeled_fit, seed=seed + folds)
    if final is None:
        raise ValueError("insufficient historical repeat-sale support for renovation classifier")
    probabilities = {
        "fit": fit_probability,
        "val": predict_transition_probability(final, val),
        "test": predict_transition_probability(final, test),
    }
    diagnostics: dict[str, object] = {
        "probability_inputs": list(PROBABILITY_INPUTS),
        "probability_feature_importance": [
            {"feature": feature, "gain": float(gain)}
            for feature, gain in sorted(
                zip(
                    final.inputs,
                    final.model.feature_importance(importance_type="gain"),
                    strict=True,
                ),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "cross_fit_folds": fold_rows,
        "fit_label_rows": labeled_fit.height,
        "fit_label_positives": int(labeled_fit["episode_high_recovery_label"].sum()),
        "fit_label_prior": final.training_prior,
        "classifier_best_iteration": final.best_iteration,
    }
    return TransitionProbabilityResult(probabilities, diagnostics, final)


def save_transition_model(
    model: CalibratedTransitionModel,
    run_dir: Path,
    *,
    diagnostics: dict[str, object] | None = None,
    cross_fitted_probabilities: pl.DataFrame | None = None,
) -> None:
    model.model.save_model(run_dir / TRANSITION_MODEL_FILE)
    metadata: dict[str, object] = {
        "inputs": list(model.inputs),
        "calibration_x": model.calibration_x.tolist(),
        "calibration_y": model.calibration_y.tolist(),
        "best_iteration": model.best_iteration,
        "training_prior": model.training_prior,
        "weak_target": "time-adjusted repeat-sale recovery >= 60% within 120-1095 days",
        "target_is_valuation_input": False,
    }
    if diagnostics is not None:
        metadata["training_diagnostics"] = diagnostics
    (run_dir / TRANSITION_METADATA_FILE).write_text(json.dumps(metadata, indent=2) + "\n")
    if cross_fitted_probabilities is not None:
        cross_fitted_probabilities.select(*_ROW_KEYS, TRANSITION_PROBABILITY_FEATURE).write_parquet(
            run_dir / TRANSITION_CROSSFIT_FILE
        )


def load_transition_model(run_dir: Path) -> CalibratedTransitionModel:
    metadata = json.loads((run_dir / TRANSITION_METADATA_FILE).read_text())
    return CalibratedTransitionModel(
        model=lgb.Booster(model_file=str(run_dir / TRANSITION_MODEL_FILE)),
        calibration_x=np.asarray(metadata["calibration_x"], dtype=np.float64),
        calibration_y=np.asarray(metadata["calibration_y"], dtype=np.float64),
        best_iteration=int(metadata["best_iteration"]),
        training_prior=float(metadata["training_prior"]),
        inputs=tuple(metadata["inputs"]),
    )


def add_persisted_transition_probability(run_dir: Path, frame: pl.DataFrame) -> pl.DataFrame:
    """Add the run-specific state probability, leaving old runs unchanged."""
    if TRANSITION_PROBABILITY_FEATURE in frame.columns:
        return frame
    metadata_path = run_dir / TRANSITION_METADATA_FILE
    model_path = run_dir / TRANSITION_MODEL_FILE
    if not metadata_path.exists() or not model_path.exists():
        return frame
    crossfit_path = run_dir / TRANSITION_CROSSFIT_FILE
    if crossfit_path.exists() and set(_ROW_KEYS).issubset(frame.columns):
        # Historical sale rows reuse their original expanding-time score.  In
        # particular, comp leaf assignment must not recompute a fit-row score
        # from a classifier whose weak target included that row's resale.
        lookup = pl.read_parquet(crossfit_path)
        out = (
            frame.with_row_index("__episode_probability_order")
            .join(lookup, on=list(_ROW_KEYS), how="left")
            .sort("__episode_probability_order")
            .drop("__episode_probability_order")
        )
        if out[TRANSITION_PROBABILITY_FEATURE].null_count() == 0:
            return out
        probability = predict_transition_probability(
            load_transition_model(run_dir), out.drop(TRANSITION_PROBABILITY_FEATURE)
        )
        return (
            out.with_columns(pl.Series("__episode_probability_fallback", probability))
            .with_columns(
                pl.coalesce(TRANSITION_PROBABILITY_FEATURE, "__episode_probability_fallback").alias(
                    TRANSITION_PROBABILITY_FEATURE
                )
            )
            .drop("__episode_probability_fallback")
        )
    probability = predict_transition_probability(load_transition_model(run_dir), frame)
    return frame.with_columns(pl.Series(TRANSITION_PROBABILITY_FEATURE, probability))
