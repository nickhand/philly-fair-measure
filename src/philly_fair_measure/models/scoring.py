"""Score properties from persisted model runs (no retraining needed)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.baseline import _encode
from philly_fair_measure.models.bayesian import load_run, predict_price_draws
from philly_fair_measure.vocab import RunKind

logger = logging.getLogger(__name__)


def latest_run_dir(kind: RunKind, data_dir: Path | None = None) -> Path:
    """Newest run directory of a given kind.

    Exact kind match, not a suffix glob: run ids are <stamp>-<kind> where the
    stamp has no dash, and one kind can be a suffix of another ("condo" vs
    "bayesian-condo")."""
    root = data_dir if data_dir is not None else config.data_dir()
    runs = sorted(
        p
        for p in (root / "models").glob("run_id=*")
        if p.name.removeprefix("run_id=").split("-", 1)[-1] == kind
    )
    if not runs:
        raise FileNotFoundError(f"no {kind} runs under {root / 'models'}; train first")
    return runs[-1]


def run_params(run_dir: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((run_dir / "params.json").read_text()))


def _lightgbm_arm_log(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(run_dir / "model_lightgbm.txt"))
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    params = run_params(run_dir)
    x = _encode(df, mappings, params["numeric_features"], params["categorical_features"])
    return np.asarray(booster.predict(x), dtype=np.float64)


def score_point(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    """THE run's point estimate: the GBM stack (LightGBM + CatBoost, persisted
    convex weight) when the run has one, the LightGBM model alone for runs
    that predate the stack — in both cases with the run's isotonic vertical
    calibration applied. This is what every point consumer (screen, ratio
    study, conformal residuals, web stats) scores with.

    If the run was trained on time-adjusted prices, the returned estimates are
    at the index reference month; the caller moves them to a date by
    multiplying with exp(-time_adj_log(date)).
    """
    from philly_fair_measure.models.baseline import (
        CATBOOST_MODEL_FILE,
        STACK_FILE,
        apply_vertical_calibration,
        catboost_frame,
    )

    pred_log = _lightgbm_arm_log(run_dir, df)
    stack_path = run_dir / STACK_FILE
    if stack_path.exists():
        from catboost import CatBoostRegressor

        params = run_params(run_dir)
        cat_model = CatBoostRegressor()
        cat_model.load_model(str(run_dir / CATBOOST_MODEL_FILE))
        cat_log = np.asarray(
            cat_model.predict(
                catboost_frame(df, params["numeric_features"], params["categorical_features"])
            ),
            dtype=np.float64,
        )
        w = float(json.loads(stack_path.read_text())["weight_lightgbm"])
        pred_log = w * pred_log + (1 - w) * cat_log
    calibration_path = run_dir / "vertical_calibration.json"
    if calibration_path.exists():
        pred_log = apply_vertical_calibration(pred_log, json.loads(calibration_path.read_text()))
    return np.asarray(np.exp(pred_log), dtype=np.float64)


def score_lightgbm(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    """The LightGBM ARM of a run (see `score_point` for the headline point).

    For stack runs the arm is returned raw — the persisted isotonic belongs to
    the stacked point, not to this arm. For pre-stack runs this IS the point
    (calibration applied), which keeps old runs and the ensemble diagnostic
    scoreable unchanged.
    """
    from philly_fair_measure.models.baseline import STACK_FILE, apply_vertical_calibration

    pred_log = _lightgbm_arm_log(run_dir, df)
    calibration_path = run_dir / "vertical_calibration.json"
    if calibration_path.exists() and not (run_dir / STACK_FILE).exists():
        pred_log = apply_vertical_calibration(pred_log, json.loads(calibration_path.read_text()))
    return np.asarray(np.exp(pred_log), dtype=np.float64)


def lightgbm_median_ratio(run_dir: Path, model: str = "point") -> float:
    """Out-of-time median estimate/price ratio of the run's point estimate — a
    transparent global calibration factor (the point undershoots recent
    appreciation slightly). model="point" falls back to the "lightgbm" row for
    runs that predate the stack; condo runs store their evaluation under
    model="condo_lightgbm"."""
    evaluation = pl.read_parquet(run_dir / "evaluation.parquet")

    def row_for(name: str) -> pl.DataFrame:
        predicate = (pl.col("model") == name) & (pl.col("segment_type") == "overall")
        if "convention" in evaluation.columns:
            predicate &= pl.col("convention") == "out_of_time"
        return evaluation.filter(predicate)

    row = row_for(model)
    if row.is_empty() and model == "point":
        row = row_for("lightgbm")
    return float(row["median_ratio"][0])


def score_quantile_heads(run_dir: Path, df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray] | None:
    """(q05, q95) REFERENCE-FRAME log-price predictions from a run's persisted
    CQR quantile heads, crossing-ordered; None when the run predates them."""
    import lightgbm as lgb

    from philly_fair_measure.models.baseline import QUANTILE_HEAD_FILES, QUANTILE_HEAD_LEVELS

    paths = {q: run_dir / QUANTILE_HEAD_FILES[q] for q in QUANTILE_HEAD_LEVELS}
    if not all(p.exists() for p in paths.values()):
        return None
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    params = run_params(run_dir)
    x = _encode(df, mappings, params["numeric_features"], params["categorical_features"])
    lo_q, hi_q = QUANTILE_HEAD_LEVELS
    lo = np.asarray(lgb.Booster(model_file=str(paths[lo_q])).predict(x), dtype=np.float64)
    hi = np.asarray(lgb.Booster(model_file=str(paths[hi_q])).predict(x), dtype=np.float64)
    return np.minimum(lo, hi), np.maximum(lo, hi)


def bayesian_median_ratio(run_dir: Path) -> float:
    """Out-of-time median estimate/price ratio of a Bayesian run — the same
    transparent global calibration convention the LightGBM point uses
    (`lightgbm_median_ratio`). The area-time slope model trades level against
    time-correlated covariates, leaving a flat few-percent bias at every
    horizon (measured 2026-07-06: 0.95 at all t_c); dividing it out once,
    from a published number, keeps screen z-scores centered."""
    evaluation = pl.read_parquet(run_dir / "evaluation.parquet")
    row = evaluation.filter(pl.col("segment_type") == "overall")
    return float(row["median_ratio"][0])


def score_bayesian_intervals(
    run_dir: Path,
    df: pl.DataFrame,
    *,
    pi_low: float = 0.05,
    pi_high: float = 0.95,
    chunk_size: int = 50_000,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(median, pi_low, pi_high) price arrays at the frame's dates; chunked to
    bound draw-matrix memory. Handles the run's time adjustment internally."""
    from datetime import date

    from philly_fair_measure.models.bayesian import _sigma_design, _time_centered, _xy

    draws, encoder, geo, basis, parcels = load_run(run_dir)
    params = run_params(run_dir)
    x = encoder.transform(df)
    area, district = geo.indices(df)
    b = basis.transform(_xy(df)) if basis is not None else None
    z = _sigma_design(df, encoder.family)
    parcel = parcels.seen(df) if parcels is not None else None
    if params.get("time_adjusted") and "time_adj_log" in df.columns:
        adj = df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    else:
        adj = np.zeros(len(x))
    # per-area time slopes (runs that trained with them persist time_ref)
    time_ref = params.get("time_ref")
    t_c = _time_centered(df, date.fromisoformat(time_ref[:10])) if time_ref else None

    medians, lows, highs = [], [], []
    for start in range(0, len(x), chunk_size):
        stop = min(start + chunk_size, len(x))
        price_draws = predict_price_draws(
            draws,
            x[start:stop],
            b[start:stop] if b is not None else None,
            z[start:stop],
            area[start:stop],
            district[start:stop],
            seed=seed + start,
            time_adj_log=adj[start:stop],
            parcel=parcel[start:stop] if parcel is not None else None,
            t_c=t_c[start:stop] if t_c is not None else None,
        )
        medians.append(np.median(price_draws, axis=0))
        lows.append(np.quantile(price_draws, pi_low, axis=0))
        highs.append(np.quantile(price_draws, pi_high, axis=0))
        logger.info("bayesian scoring: %s/%s rows", f"{stop:,}", f"{len(x):,}")
    return np.concatenate(medians), np.concatenate(lows), np.concatenate(highs)
