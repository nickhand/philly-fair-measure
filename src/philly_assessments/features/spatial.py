"""As-of k-nearest-sales price surface — the principled version of OPA's
`SPATIAL` covariate (docs/feature-plan-v2.md §1.3).

For each target, the feature is the distance-weighted mean of the
*time-adjusted* log $/sqft of the k nearest arms-length sales that occurred
strictly earlier, excluding the target's own parcel. Trees can't interpolate
space smoothly and area dummies step at boundaries; this surface carries the
between-block gradient.

Leakage discipline for training targets: sales are blocked by quarter, and
each quarter's targets query a KD-tree built only from sales in *prior*
quarters (never the same quarter, so never the future). Scoring at a fixed
valuation date uses a single tree over the trailing window.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

KNN_K = 15
DIST_SOFTENING_M = 100.0
SCORE_WINDOW_DAYS = 1825
_EXTRA = 4  # over-query to survive same-parcel exclusion


def _weighted_knn(
    tree: cKDTree,
    tree_parcels: np.ndarray,
    tree_values: np.ndarray,
    xy: np.ndarray,
    parcels: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(weighted mean value, n used, mean distance) per query row."""
    n_query = len(xy)
    out_val = np.full(n_query, np.nan)
    out_n = np.zeros(n_query, dtype=np.int32)
    out_dist = np.full(n_query, np.nan)
    if tree.n == 0:
        return out_val, out_n, out_dist
    kq = min(k + _EXTRA, tree.n)
    dist, ix = tree.query(xy, k=kq)
    if kq == 1:
        dist, ix = dist[:, None], ix[:, None]
    for row in range(n_query):
        mask = tree_parcels[ix[row]] != parcels[row]
        d = dist[row][mask][:k]
        v = tree_values[ix[row]][mask][:k]
        if len(v) == 0:
            continue
        w = 1.0 / (d + DIST_SOFTENING_M)
        out_val[row] = float(np.sum(w * v) / np.sum(w))
        out_n[row] = len(v)
        out_dist[row] = float(d.mean())
    return out_val, out_n, out_dist


def knn_ppsf_for_sales(points: pl.DataFrame, *, k: int = KNN_K) -> pl.DataFrame:
    """Per-sale surface features from strictly earlier sales (quarter-blocked).

    `points` columns: sale_id, parcel_id, x_m, y_m, sale_date, adj_log_ppsf.
    """
    from scipy.spatial import cKDTree

    pts = points.sort("sale_date").with_columns(
        pl.col("sale_date").dt.truncate("1q").alias("_quarter")
    )
    xy = pts.select("x_m", "y_m").to_numpy()
    parcels = pts["parcel_id"].to_numpy()
    values = pts["adj_log_ppsf"].to_numpy()
    quarters = pts["_quarter"].to_numpy()

    out_val = np.full(len(pts), np.nan)
    out_n = np.zeros(len(pts), dtype=np.int32)
    out_dist = np.full(len(pts), np.nan)
    boundaries = np.unique(quarters)
    for quarter in boundaries:
        past = quarters < quarter
        current = quarters == quarter
        if not past.any():
            continue
        tree = cKDTree(xy[past])
        val, n, dist = _weighted_knn(
            tree, parcels[past], values[past], xy[current], parcels[current], k
        )
        out_val[current] = val
        out_n[current] = n
        out_dist[current] = dist

    return pts.select("sale_id").with_columns(
        pl.Series("mkt_knn_log_ppsf", out_val).fill_nan(None),
        pl.Series("mkt_knn_n", out_n),
        pl.Series("mkt_knn_mean_dist_m", out_dist).fill_nan(None),
    )


def knn_ppsf_at_date(
    points: pl.DataFrame,
    targets: pl.DataFrame,
    valuation_date: datetime,
    *,
    k: int = KNN_K,
    window_days: int = SCORE_WINDOW_DAYS,
) -> pl.DataFrame:
    """Per-parcel surface features at a valuation date (single trailing-window tree).

    `targets` columns: parcel_id, x_m, y_m. Own-parcel sales are excluded.
    """
    from scipy.spatial import cKDTree

    window = points.filter(
        (pl.col("sale_date") < valuation_date)
        & ((pl.lit(valuation_date) - pl.col("sale_date")).dt.total_days() <= window_days)
    )
    tree = cKDTree(window.select("x_m", "y_m").to_numpy()) if window.height else None
    if tree is None or tree.n == 0:
        return targets.select("parcel_id").with_columns(
            pl.lit(None, dtype=pl.Float64).alias("mkt_knn_log_ppsf"),
            pl.lit(0).alias("mkt_knn_n"),
            pl.lit(None, dtype=pl.Float64).alias("mkt_knn_mean_dist_m"),
        )
    val, n, dist = _weighted_knn(
        tree,
        window["parcel_id"].to_numpy(),
        window["adj_log_ppsf"].to_numpy(),
        targets.select("x_m", "y_m").to_numpy(),
        targets["parcel_id"].to_numpy(),
        k,
    )
    return targets.select("parcel_id").with_columns(
        pl.Series("mkt_knn_log_ppsf", val).fill_nan(None),
        pl.Series("mkt_knn_n", n),
        pl.Series("mkt_knn_mean_dist_m", dist).fill_nan(None),
    )
