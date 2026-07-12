"""Conformalized stacking: one point from both arms, honest intervals around it.

The screen's two machines disagree in character: LightGBM is sharp but drifts
hot in segments (measured 2026-07-06: median est/sale 1.10-1.13 on d_10
pre-war rows vs 1.04 citywide), while the Bayesian median is spatially
disciplined but smoother. The textbook remedy is a convex log-space stack —
one weight, fit where both models are out-of-sample — and a split-conformal
band around the stacked point so the interval inherits a finite-sample
coverage guarantee no matter how wrong either arm is.

Honesty protocol: both runs trained on everything before the shared
out-of-time test slice, so that slice is the only data neither model has
seen. It is split chronologically in half — the earlier half fits the stack
weight and calibrates the conformal offsets, the later half is touched once,
for evaluation. `fair-measure ensemble-check` prints the comparison table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure.models.conformal import (
    KNN_K,
    CalibrationSet,
    conformal_offsets,
    split_frames,
    xy_district,
)
from philly_fair_measure.models.metrics import evaluate_estimates, stack_weight
from philly_fair_measure.models.scoring import (
    latest_run_dir,
    run_params,
    score_bayesian_intervals,
    score_lightgbm,
)

__all__ = ["EnsembleCheckResult", "ensemble_check", "stack_weight"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnsembleCheckResult:
    baseline_run: Path
    bayesian_run: Path
    weight_lightgbm: float
    points: pl.DataFrame  # point metrics per estimator, evaluation half
    intervals: pl.DataFrame  # coverage/width per interval system, evaluation half


def _interval_row(name: str, lo: np.ndarray, hi: np.ndarray, y: np.ndarray) -> dict[str, object]:
    covered = (y >= lo) & (y <= hi)
    return {
        "interval": name,
        "coverage": float(covered.mean()),
        "median_width_ratio": float(np.median(hi / lo)),
        "mean_width_rel": float(np.mean((hi - lo) / y)),
    }


def ensemble_check(
    data_dir: Path | None = None,
    *,
    alpha: float = 0.10,
    k: int = KNN_K,
) -> EnsembleCheckResult:
    baseline_run = latest_run_dir("baseline", data_dir)
    bayesian_run = latest_run_dir("bayesian", data_dir)
    _, _, test_df = split_frames(baseline_run, data_dir)

    # both arms in the sale-date frame, comparable to raw sale prices
    lgb = score_lightgbm(baseline_run, test_df)
    if run_params(baseline_run).get("time_adjusted"):
        lgb = lgb * np.exp(-test_df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy())
    bayes_median, bayes_lo, bayes_hi = score_bayesian_intervals(bayesian_run, test_df)
    y = test_df["sale_price"].cast(pl.Float64).to_numpy()
    ok = (y > 0) & (lgb > 0) & (bayes_median > 0)
    if not ok.all():
        logger.info("dropping %d test rows with non-positive prices/estimates", int((~ok).sum()))

    log_lgb, log_bayes, log_y = np.log(lgb[ok]), np.log(bayes_median[ok]), np.log(y[ok])
    xy, district = xy_district(test_df.filter(pl.Series(ok)))
    b_lo, b_hi = bayes_lo[ok], bayes_hi[ok]
    y_ok = y[ok]

    # chronological halves of the only slice neither model trained on
    n = len(log_y)
    n_cal = n // 2
    cal, ev = np.arange(n) < n_cal, np.arange(n) >= n_cal

    w = stack_weight(log_lgb[cal], log_bayes[cal], log_y[cal])
    logger.info("stack weight on lightgbm: %.3f (calibration n=%d)", w, n_cal)
    log_stack = w * log_lgb + (1 - w) * log_bayes

    def knn_band(log_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        calib = CalibrationSet(
            residual=log_y[cal] - log_pred[cal], xy=xy[cal], district=district[cal]
        )
        lo_off, hi_off = conformal_offsets(
            calib, xy[ev], district[ev], alpha=alpha, method="knn", k=k
        )
        return np.exp(log_pred[ev] + lo_off), np.exp(log_pred[ev] + hi_off)

    stack_lo, stack_hi = knn_band(log_stack)
    lgb_lo, lgb_hi = knn_band(log_lgb)

    points = pl.DataFrame(
        [
            {"estimator": name, **evaluate_estimates(np.exp(pred[ev]), y_ok[ev]).as_row()}
            for name, pred in (
                ("lightgbm", log_lgb),
                ("bayesian_median", log_bayes),
                ("ensemble", log_stack),
            )
        ]
    )
    intervals = pl.DataFrame(
        [
            _interval_row("bayesian_posterior", b_lo[ev], b_hi[ev], y_ok[ev]),
            _interval_row("conformal_knn_lightgbm", lgb_lo, lgb_hi, y_ok[ev]),
            _interval_row("conformal_knn_ensemble", stack_lo, stack_hi, y_ok[ev]),
        ]
    )
    return EnsembleCheckResult(
        baseline_run=baseline_run,
        bayesian_run=bayesian_run,
        weight_lightgbm=w,
        points=points,
        intervals=intervals,
    )
