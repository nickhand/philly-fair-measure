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


def score_lightgbm(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    """Price estimates from a persisted run, using the run's own feature lists.

    If the run was trained on time-adjusted prices, the returned estimates are
    at the index reference month; the caller moves them to a date by
    multiplying with exp(-time_adj_log(date)).
    """
    import lightgbm as lgb

    from philly_fair_measure.models.baseline import apply_vertical_calibration

    booster = lgb.Booster(model_file=str(run_dir / "model_lightgbm.txt"))
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    params = run_params(run_dir)
    x = _encode(df, mappings, params["numeric_features"], params["categorical_features"])
    pred_log = booster.predict(x)
    calibration_path = run_dir / "vertical_calibration.json"
    if calibration_path.exists():
        pred_log = apply_vertical_calibration(pred_log, json.loads(calibration_path.read_text()))
    return np.exp(pred_log)


def lightgbm_median_ratio(run_dir: Path, model: str = "lightgbm") -> float:
    """Out-of-time median estimate/price ratio of the run — a transparent global
    calibration factor (the baseline undershoots recent appreciation slightly).
    Condo runs store their evaluation under model="condo_lightgbm"."""
    evaluation = pl.read_parquet(run_dir / "evaluation.parquet")
    predicate = (pl.col("model") == model) & (pl.col("segment_type") == "overall")
    if "convention" in evaluation.columns:
        predicate &= pl.col("convention") == "out_of_time"
    row = evaluation.filter(predicate)
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
    from philly_fair_measure.models.bayesian import _sigma_design, _xy

    draws, encoder, geo, basis, parcels = load_run(run_dir)
    x = encoder.transform(df)
    area, district = geo.indices(df)
    b = basis.transform(_xy(df)) if basis is not None else None
    z = _sigma_design(df, encoder.family)
    parcel = parcels.seen(df) if parcels is not None else None
    if run_params(run_dir).get("time_adjusted") and "time_adj_log" in df.columns:
        adj = df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    else:
        adj = np.zeros(len(x))

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
        )
        medians.append(np.median(price_draws, axis=0))
        lows.append(np.quantile(price_draws, pi_low, axis=0))
        highs.append(np.quantile(price_draws, pi_high, axis=0))
        logger.info("bayesian scoring: %s/%s rows", f"{stop:,}", f"{len(x):,}")
    return np.concatenate(medians), np.concatenate(lows), np.concatenate(highs)
