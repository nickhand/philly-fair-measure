"""Score properties from persisted model runs (no retraining needed)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config
from philly_assessments.models.baseline import _encode
from philly_assessments.models.bayesian import load_run, predict_price_draws

logger = logging.getLogger(__name__)


def latest_run_dir(kind: str, data_dir: Path | None = None) -> Path:
    """Newest run directory of a given kind ("baseline" or "bayesian")."""
    root = data_dir if data_dir is not None else config.data_dir()
    runs = sorted((root / "models").glob(f"run_id=*-{kind}"))
    if not runs:
        raise FileNotFoundError(f"no {kind} runs under {root / 'models'}; train first")
    return runs[-1]


def run_params(run_dir: Path) -> dict:
    return json.loads((run_dir / "params.json").read_text())


def score_lightgbm(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    """Price estimates from a persisted run, using the run's own feature lists.

    If the run was trained on time-adjusted prices, the returned estimates are
    at the index reference month; the caller moves them to a date by
    multiplying with exp(-time_adj_log(date)).
    """
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(run_dir / "model_lightgbm.txt"))
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    params = run_params(run_dir)
    x = _encode(df, mappings, params["numeric_features"], params["categorical_features"])
    return np.exp(booster.predict(x))


def lightgbm_median_ratio(run_dir: Path) -> float:
    """Out-of-time median estimate/price ratio of the run — a transparent global
    calibration factor (the baseline undershoots recent appreciation slightly)."""
    evaluation = pl.read_parquet(run_dir / "evaluation.parquet")
    row = evaluation.filter(
        (pl.col("model") == "lightgbm") & (pl.col("segment_type") == "overall")
    )
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
    """(median, pi_low, pi_high) price arrays; chunked to bound draw-matrix memory."""
    draws, encoder, geo = load_run(run_dir)
    x = encoder.transform(df)
    tract, ward = geo.tract_indices(df)
    medians, lows, highs = [], [], []
    for start in range(0, len(x), chunk_size):
        stop = min(start + chunk_size, len(x))
        price_draws = predict_price_draws(
            draws, x[start:stop], tract[start:stop], ward[start:stop], seed=seed + start
        )
        medians.append(np.median(price_draws, axis=0))
        lows.append(np.quantile(price_draws, pi_low, axis=0))
        highs.append(np.quantile(price_draws, pi_high, axis=0))
        logger.info("bayesian scoring: %s/%s rows", f"{stop:,}", f"{len(x):,}")
    return np.concatenate(medians), np.concatenate(lows), np.concatenate(highs)
