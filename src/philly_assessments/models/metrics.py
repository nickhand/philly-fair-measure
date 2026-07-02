"""Evaluation metrics: standard fit statistics plus IAAO ratio-study statistics.

Ratio statistics come from assesspy (the CCAO's package; see docs/ccao-lessons.md):

    COD  coefficient of dispersion — uniformity; IAAO single-family target <= 15
    PRD  price-related differential — vertical equity; > ~1.03 means regressive
         (cheap homes over-assessed relative to expensive ones)
    PRB  price-related bias coefficient — target within [-0.05, 0.05]

All functions take plain sequences/arrays of positive prices; rows where either
value is missing or non-positive are dropped before computing.
"""

from __future__ import annotations

import math

import assesspy
import numpy as np


def _clean(estimate, sale_price) -> tuple[np.ndarray, np.ndarray]:
    est = np.asarray(estimate, dtype=np.float64)
    sale = np.asarray(sale_price, dtype=np.float64)
    mask = np.isfinite(est) & np.isfinite(sale) & (est > 0) & (sale > 0)
    return est[mask], sale[mask]


def fit_metrics(estimate, sale_price) -> dict[str, float | int | None]:
    est, sale = _clean(estimate, sale_price)
    if len(est) == 0:
        return {"n": 0, "rmse_log": None, "mape": None, "r2_log": None}
    log_err = np.log(est) - np.log(sale)
    ss_tot = float(np.sum((np.log(sale) - np.log(sale).mean()) ** 2))
    return {
        "n": int(len(est)),
        "rmse_log": float(np.sqrt(np.mean(log_err**2))),
        "mape": float(np.mean(np.abs(est - sale) / sale)),
        "r2_log": (1.0 - float(np.sum(log_err**2)) / ss_tot) if ss_tot > 0 else None,
    }


def ratio_metrics(estimate, sale_price) -> dict[str, float | None]:
    est, sale = _clean(estimate, sale_price)
    if len(est) < 3:
        return {"median_ratio": None, "cod": None, "prd": None, "prb": None}
    ratio = est / sale
    out: dict[str, float | None] = {"median_ratio": float(np.median(ratio))}
    for name, fn in (("cod", assesspy.cod), ("prd", assesspy.prd), ("prb", assesspy.prb)):
        try:
            value = float(fn(est, sale))
            out[name] = value if math.isfinite(value) else None
        except Exception:  # degenerate inputs (e.g. zero variance) — report absence, not a crash
            out[name] = None
    return out


def evaluate_estimates(estimate, sale_price) -> dict[str, float | int | None]:
    return {**fit_metrics(estimate, sale_price), **ratio_metrics(estimate, sale_price)}
