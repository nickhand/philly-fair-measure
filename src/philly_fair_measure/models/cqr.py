"""Spatially weighted conformalized quantile regression (CQR) — the bake-off.

Fixed-offset conformal (models/conformal.py) adapts interval WIDTH to
geography but not to features: two homes at the same address get the same
offsets regardless of what they are. CQR (Romano, Patterson & Candès 2019)
starts from feature-adaptive quantile heads and conformalizes their miss:

    q05, q95      LightGBM quantile regressors on the run's own design matrix
    E_i           max(q05(x_i) − y_i, y_i − q95(x_i))   (conformity score)
    Q             finite-sample (1−α)-quantile of E on calibration rows
    interval      [q05 − Q, q95 + Q]                     (log space)

The spatially weighted variant computes Q per target from the k nearest
calibration scores (same weighting machinery as conformal.py), marrying
feature-adaptive shape with local calibration.

Honesty protocol: the quantile heads train on the run's FIT slice only, so
the validation slice is clean calibration for them (cleaner than it is for
the point model, which used it for early stopping), and the full out-of-time
test slice is touched once, for the comparison table. `fair-measure
cqr-check` prints coverage/width for CQR-global and CQR-knn next to the
Bayesian posterior and fixed-offset conformal-knn, overall and by district /
price quintile. This is Stage 3 of the robustness plan: machinery + numbers;
whether CQR replaces the current interval anchor is a product decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from philly_fair_measure.models.conformal import (
    ALPHA,
    KNN_K,
    SOFTENING_M,
    CalibrationSet,
    conformal_offsets,
    frame_residuals,
    split_frames,
    xy_district,
)
from philly_fair_measure.models.scoring import latest_run_dir, run_params

logger = logging.getLogger(__name__)

_LGB_QUANTILE_PARAMS: dict[str, Any] = {
    "n_estimators": 600,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 40,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "verbose": -1,
}


def cqr_score(y: np.ndarray, q_lo: np.ndarray, q_hi: np.ndarray) -> np.ndarray:
    """CQR conformity score: how far outside [q_lo, q_hi] the truth fell
    (negative when inside)."""
    return np.asarray(np.maximum(q_lo - y, y - q_hi), dtype=np.float64)


def _global_correction(scores: np.ndarray, alpha: float) -> float:
    """Finite-sample (1−α) empirical quantile of the conformity scores."""
    n = len(scores)
    if n == 0:
        return np.inf
    ix = min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)
    return float(np.sort(scores)[ix])


def _knn_correction(
    scores: np.ndarray,
    cal_xy: np.ndarray,
    xy: np.ndarray,
    *,
    alpha: float,
    k: int,
    softening_m: float = SOFTENING_M,
    chunk_size: int = 25_000,
) -> np.ndarray:
    """Per-target spatially weighted correction: the (1−α)(1+1/k)-weighted
    quantile of the k nearest calibration scores; global fallback where the
    target (or the whole calibration set) has no coordinates."""
    from scipy.spatial import cKDTree

    from philly_fair_measure.models.conformal import _weighted_upper

    out = np.full(len(xy), _global_correction(scores, alpha))
    cal_ok = np.isfinite(cal_xy).all(axis=1)
    if not cal_ok.any():
        return out
    tree = cKDTree(cal_xy[cal_ok])
    s_cal = scores[cal_ok]
    kk = min(k, tree.n)
    level = min(1.0, (1 - alpha) * (kk + 1) / kk)
    targets = np.flatnonzero(np.isfinite(xy).all(axis=1))
    for start in range(0, len(targets), chunk_size):
        rows = targets[start : start + chunk_size]
        dist, ix = tree.query(xy[rows], k=kk, workers=-1)
        if kk == 1:
            dist, ix = dist[:, None], ix[:, None]
        out[rows] = _weighted_upper(s_cal[ix], 1.0 / (dist + softening_m), level)
    return out


def cqr_band_for_frame(
    run_dir: Path,
    df: pl.DataFrame,
    data_dir: Path | None = None,
    *,
    alpha: float = ALPHA,
    k: int = KNN_K,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Spatially weighted CQR band (price levels, in `df`'s own date frame)
    from a run's persisted quantile heads — the screen's second uncertainty
    machine (Stage 3b). Calibrates on the run's validation slice, which the
    heads never trained on. Returns None for runs that predate the heads
    (callers fall back to the fixed-offset conformal band)."""
    from philly_fair_measure.models.scoring import score_quantile_heads

    target_bands = score_quantile_heads(run_dir, df)
    if target_bands is None:
        return None
    _, val_df, _ = split_frames(run_dir, data_dir)
    val_bands = score_quantile_heads(run_dir, val_df)
    assert val_bands is not None  # same run as target_bands
    scores = cqr_score(_adjusted_log_price(run_dir, val_df), *val_bands)
    xy_val, _ = xy_district(val_df)
    ok = np.isfinite(scores)
    corr = _knn_correction(scores[ok], xy_val[ok], xy_district(df)[0], alpha=alpha, k=k)
    # heads predict reference-frame log prices; shift to the frame's dates
    # (same convention as the point model in the screen)
    adj = (
        df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
        if run_params(run_dir).get("time_adjusted") and "time_adj_log" in df.columns
        else np.zeros(df.height)
    )
    t_lo, t_hi = target_bands
    return np.exp(t_lo - corr - adj), np.exp(t_hi + corr - adj)


@dataclass(frozen=True)
class CqrCheckResult:
    run_dir: Path
    table: pl.DataFrame  # coverage/width by method × segment
    district_coverage: pl.DataFrame  # min/max span per method


def _adjusted_log_price(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    y = np.log(df["sale_price"].to_numpy())
    if run_params(run_dir).get("time_adjusted"):
        y = y + df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    return np.asarray(y, dtype=np.float64)


def cqr_check(
    data_dir: Path | None = None,
    *,
    alpha: float = ALPHA,
    k: int = KNN_K,
    seed: int = 42,
) -> CqrCheckResult:
    import json

    import lightgbm as lgb

    from philly_fair_measure.models.baseline import _encode
    from philly_fair_measure.models.scoring import prepare_model_frame, score_bayesian_intervals

    run_dir = latest_run_dir("baseline", data_dir)
    fit_df, val_df, test_df = split_frames(run_dir, data_dir)
    fit_df = prepare_model_frame(run_dir, fit_df)
    val_df = prepare_model_frame(run_dir, val_df)
    test_df = prepare_model_frame(run_dir, test_df)
    params = run_params(run_dir)
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    numeric, categorical = params["numeric_features"], params["categorical_features"]

    x_fit = _encode(fit_df, mappings, numeric, categorical)
    y_fit = _adjusted_log_price(run_dir, fit_df)
    heads: dict[float, lgb.LGBMRegressor] = {}
    for q in (alpha / 2, 1 - alpha / 2):
        model = lgb.LGBMRegressor(
            objective="quantile", alpha=q, random_state=seed, **_LGB_QUANTILE_PARAMS
        )
        model.fit(x_fit, y_fit)
        heads[q] = model
        logger.info("quantile head q=%.3f trained on %s fit rows", q, f"{len(x_fit):,}")

    def head_bands(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = _encode(df, mappings, numeric, categorical)
        lo = np.asarray(heads[alpha / 2].predict(x), dtype=np.float64)
        hi = np.asarray(heads[1 - alpha / 2].predict(x), dtype=np.float64)
        # quantile crossings are rare but possible; order them
        return np.minimum(lo, hi), np.maximum(lo, hi)

    # calibration: conformity scores on the validation slice (unseen by heads)
    v_lo, v_hi = head_bands(val_df)
    y_val = _adjusted_log_price(run_dir, val_df)
    scores = cqr_score(y_val, v_lo, v_hi)
    xy_val, district_val = xy_district(val_df)
    ok = np.isfinite(scores)
    scores, xy_val, district_val = scores[ok], xy_val[ok], district_val[ok]

    # evaluation: the untouched out-of-time test slice
    t_lo, t_hi = head_bands(test_df)
    y_test = _adjusted_log_price(run_dir, test_df)
    xy_t, district_t = xy_district(test_df)
    price = test_df["sale_price"].to_numpy()

    covered: dict[str, np.ndarray] = {}
    width: dict[str, np.ndarray] = {}

    q_global = _global_correction(scores, alpha)
    covered["cqr_global"] = (y_test >= t_lo - q_global) & (y_test <= t_hi + q_global)
    width["cqr_global"] = (t_hi - t_lo) + 2 * q_global

    q_knn = _knn_correction(scores, xy_val, xy_t, alpha=alpha, k=k)
    covered["cqr_knn"] = (y_test >= t_lo - q_knn) & (y_test <= t_hi + q_knn)
    width["cqr_knn"] = (t_hi - t_lo) + 2 * q_knn

    # incumbents: fixed-offset conformal-knn and the Bayesian posterior
    cal = CalibrationSet(
        residual=frame_residuals(run_dir, val_df)[ok], xy=xy_val, district=district_val
    )
    off_lo, off_hi = conformal_offsets(cal, xy_t, district_t, alpha=alpha, method="knn", k=k)
    test_resid = frame_residuals(run_dir, test_df)
    covered["conformal_knn"] = (test_resid >= off_lo) & (test_resid <= off_hi)
    width["conformal_knn"] = off_hi - off_lo

    bayes_run = latest_run_dir("bayesian", data_dir)
    _, b_lo, b_hi = score_bayesian_intervals(
        bayes_run, test_df, pi_low=alpha / 2, pi_high=1 - alpha / 2
    )
    covered["bayesian"] = (price >= b_lo) & (price <= b_hi)
    width["bayesian"] = np.log(b_hi / b_lo)

    from philly_fair_measure.models.conformal import _segment_masks

    rows = []
    for method in covered:
        for seg_type, seg, mask in _segment_masks(test_df, price):
            if not mask.any():
                continue
            rows.append(
                {
                    "method": method,
                    "segment_type": seg_type,
                    "segment": seg,
                    "n": int(mask.sum()),
                    "coverage": float(covered[method][mask].mean()),
                    "median_width_log": float(np.median(width[method][mask])),
                    "nominal": 1 - alpha,
                }
            )
    table = pl.DataFrame(rows)

    d_rows = []
    for method in covered:
        for label in np.unique(district_t):
            mask = district_t == label
            if not label or int(mask.sum()) < 100:
                continue
            d_rows.append(
                {
                    "method": method,
                    "district": str(label),
                    "n": int(mask.sum()),
                    "coverage": float(covered[method][mask].mean()),
                }
            )
    district_coverage = pl.DataFrame(d_rows)

    table.write_parquet(run_dir / "cqr_check.parquet")
    district_coverage.write_parquet(run_dir / "cqr_district_coverage.parquet")
    return CqrCheckResult(run_dir=run_dir, table=table, district_coverage=district_coverage)
