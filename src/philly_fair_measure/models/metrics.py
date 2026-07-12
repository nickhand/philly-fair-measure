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

import numpy as np
import numpy.typing as npt


def stack_weight(
    log_a: npt.NDArray[np.float64], log_b: npt.NDArray[np.float64], log_y: npt.NDArray[np.float64]
) -> float:
    """Least-squares weight for w*a + (1-w)*b vs y in log space, clipped to
    [0, 1] so the stack stays a convex blend (never an extrapolation). Shared
    by the trained GBM stack (models/baseline.py) and the ensemble diagnostic
    (models/ensemble.py)."""
    d = log_a - log_b
    denom = float(d @ d)
    if denom <= 0.0:
        return 0.5
    return float(np.clip((d @ (log_y - log_b)) / denom, 0.0, 1.0))


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
    # deferred: assesspy is a training-only dependency, absent from the serve
    # image (requirements.serve.txt) whose API imports this module transitively
    import assesspy

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


@dataclass(frozen=True)
class VEIGroup:
    """One percentile group of the VEI test."""

    n: int
    median_proxy: float
    median_ratio: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class VEIResult:
    """IAAO Vertical Equity Indicator (2025 Standard on Ratio Studies exposure
    draft, §8.2.1). Negative VEI = regressive tendency, positive = progressive;
    |VEI| ≤ 10% is acceptable outright, and beyond that the verdict rests on
    whether the first/last group medians differ provably by more than 10%."""

    vei: float | None  # 100 * (median last PG - median first PG) / sample median
    significance: float | None  # the CI-gap statistic; only set when |VEI| > 10
    verdict: str  # "acceptable" | "unacceptable" | "insufficient_sample"
    n: int
    n_groups: int
    groups: tuple[VEIGroup, ...]


def _median_ci(ratios: np.ndarray, z: float) -> tuple[float, float]:
    """Distribution-free median confidence interval (§7.5.3): rank offset
    ceil(z*sqrt(n)/2 [+0.5 if n even]) counted out from the median."""
    r = np.sort(ratios)
    n = len(r)
    offset = z * math.sqrt(n) / 2.0
    if n % 2 == 0:
        offset += 0.5
    o = math.ceil(offset)
    if n % 2 == 1:
        mid = (n - 1) // 2
        lo_i, hi_i = mid - o, mid + o
    else:
        lo_i, hi_i = n // 2 - o, n // 2 - 1 + o
    return float(r[max(0, lo_i)]), float(r[min(n - 1, hi_i)])


def vertical_equity_indicator(
    estimate: npt.ArrayLike, sale_price: npt.ArrayLike, *, z: float = 1.64
) -> VEIResult:
    """The VEI test exactly as specified in the IAAO 2025 exposure draft:

    1. ratio = AV / SP; 2. market-value proxy = 0.5*SP + 0.5*(AV / median
    ratio), which de-biases the proxy toward neither regressivity (pure SP)
    nor progressivity (pure AV); 3. sort by proxy and split into percentile
    groups — halves for n 20–50, quartiles 51–500, deciles 501+; 4. per-group
    median ratio and 90% median CI (z=1.64 per the standard's own arithmetic);
    5. VEI = 100 * (last-group median − first-group median) / sample median;
    6. if |VEI| > 10 and the first/last CIs do not overlap, the significance
    statistic is the gap between the closest CI bounds scaled the same way —
    above 10 the inequity is provably outside acceptable limits.
    """
    av, sp = _clean(estimate, sale_price)
    n = len(av)
    if n < 20:  # §9: below two groups of 10 the comparison is not meaningful
        return VEIResult(None, None, "insufficient_sample", n, 0, ())
    n_groups = 2 if n <= 50 else 4 if n <= 500 else 10

    ratio = av / sp
    sample_median = float(np.median(ratio))
    proxy = 0.5 * sp + 0.5 * (av / sample_median)
    order = np.argsort(proxy, kind="stable")
    # percentile-rank grouping: rank r (0-based) -> floor(r * G / n), which
    # reproduces the standard's worked example (54 sales -> 14/13/14/13)
    assignment = (np.arange(n) * n_groups) // n

    groups: list[VEIGroup] = []
    for g in range(n_groups):
        members = order[assignment == g]
        lo, hi = _median_ci(ratio[members], z)
        groups.append(
            VEIGroup(
                n=len(members),
                median_proxy=float(np.median(proxy[members])),
                median_ratio=float(np.median(ratio[members])),
                ci_low=lo,
                ci_high=hi,
            )
        )

    first, last = groups[0], groups[-1]
    vei = 100.0 * (last.median_ratio - first.median_ratio) / sample_median
    if abs(vei) <= 10.0:
        return VEIResult(vei, None, "acceptable", n, n_groups, tuple(groups))
    high, low = (last, first) if last.median_ratio >= first.median_ratio else (first, last)
    if high.ci_low <= low.ci_high:  # intervals overlap: not provably unacceptable
        return VEIResult(vei, None, "acceptable", n, n_groups, tuple(groups))
    significance = 100.0 * (high.ci_low - low.ci_high) / sample_median
    verdict = "unacceptable" if significance > 10.0 else "acceptable"
    return VEIResult(vei, significance, verdict, n, n_groups, tuple(groups))
