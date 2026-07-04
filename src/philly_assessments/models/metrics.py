"""Evaluation metrics: standard fit statistics plus IAAO ratio-study statistics.

Ratio statistics come from assesspy (the CCAO's package; see docs/ccao-lessons.md):

    COD  coefficient of dispersion — uniformity; IAAO single-family target <= 15
    PRD  price-related differential — vertical equity; > ~1.03 means regressive
         (cheap homes over-assessed relative to expensive ones)
    PRB  price-related bias coefficient — target within [-0.05, 0.05]

All functions take plain sequences/arrays of positive prices; rows where either
value is missing or non-positive are dropped before computing. Results are
frozen dataclasses (Robust Python: typed attributes instead of stringly-keyed
dicts); a statistic that is undefined on the cleaned input is ``None``, never
a crash.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import assesspy
import numpy as np
import numpy.typing as npt


def _clean(
    estimate: npt.ArrayLike, sale_price: npt.ArrayLike
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    est = np.asarray(estimate, dtype=np.float64)
    sale = np.asarray(sale_price, dtype=np.float64)
    mask = np.isfinite(est) & np.isfinite(sale) & (est > 0) & (sale > 0)
    return est[mask], sale[mask]


@dataclass(frozen=True)
class FitMetrics:
    """Fit statistics on the cleaned pairs; ``None`` when the input is empty."""

    n: int
    rmse_log: float | None
    mape: float | None
    r2_log: float | None


@dataclass(frozen=True)
class RatioMetrics:
    """IAAO ratio-study statistics; ``None`` when undefined (< 3 sales or
    degenerate inputs)."""

    median_ratio: float | None
    cod: float | None
    prd: float | None
    prb: float | None
    mki: float | None


@dataclass(frozen=True)
class Metrics(RatioMetrics, FitMetrics):
    """One evaluation result: fit + ratio statistics.

    ``as_row()`` flattens to the historical evaluation-table column set
    (n, rmse_log, mape, r2_log, median_ratio, cod, prd, prb, mki) for
    DataFrame row construction.
    """

    def as_row(self) -> dict[str, float | int | None]:
        return asdict(self)


def fit_metrics(estimate: npt.ArrayLike, sale_price: npt.ArrayLike) -> FitMetrics:
    est, sale = _clean(estimate, sale_price)
    if len(est) == 0:
        return FitMetrics(n=0, rmse_log=None, mape=None, r2_log=None)
    log_err = np.log(est) - np.log(sale)
    ss_tot = float(np.sum((np.log(sale) - np.log(sale).mean()) ** 2))
    return FitMetrics(
        n=int(len(est)),
        rmse_log=float(np.sqrt(np.mean(log_err**2))),
        mape=float(np.mean(np.abs(est - sale) / sale)),
        r2_log=(1.0 - float(np.sum(log_err**2)) / ss_tot) if ss_tot > 0 else None,
    )


def ratio_metrics(estimate: npt.ArrayLike, sale_price: npt.ArrayLike) -> RatioMetrics:
    est, sale = _clean(estimate, sale_price)
    if len(est) < 3:
        return RatioMetrics(median_ratio=None, cod=None, prd=None, prb=None, mki=None)

    def safe(fn: Callable[[np.ndarray, np.ndarray], Any]) -> float | None:
        try:
            value = float(fn(est, sale))
        except Exception:  # degenerate inputs (e.g. zero variance) — report absence, not a crash
            return None
        return value if math.isfinite(value) else None

    return RatioMetrics(
        median_ratio=float(np.median(est / sale)),
        cod=safe(assesspy.cod),
        prd=safe(assesspy.prd),
        prb=safe(assesspy.prb),
        mki=safe(assesspy.mki),
    )


def evaluate_estimates(estimate: npt.ArrayLike, sale_price: npt.ArrayLike) -> Metrics:
    fit = fit_metrics(estimate, sale_price)
    ratio = ratio_metrics(estimate, sale_price)
    return Metrics(**asdict(fit), **asdict(ratio))
