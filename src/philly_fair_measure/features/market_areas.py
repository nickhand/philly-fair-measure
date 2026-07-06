"""Learned market areas: a data-driven analog of OPA's Geographic Market Areas.

OPA maintains 600+ hand-drawn GMAs, published only as PDF maps (verified
2026-07-02). This module learns a comparable partition from arms-length sales:
k-means over (projected x, projected y, month-detrended log $/sqft), then every
residential parcel is assigned by majority vote of its k nearest sale points.
Clustering on coordinates plus a smooth price level yields areas whose
boundaries follow price discontinuities — the property GMAs are designed to
capture (see docs/feature-plan-v2.md §1.2).

Because the price dimension can pull spatially-separated pockets into one
cluster, a post-hoc pass (`_enforce_contiguity`) then guarantees every final
market area is a single connected blob: a disconnected pocket large enough to
stand on its own becomes a new area (inheriting its parent's price level and
district); smaller strays merge into the nearest area.

Market areas are grouped into ~18 districts (k-means on area centroids), the
geography used by the monthly price index (price_index.py) — coarse enough for
monthly sale counts, fine enough to separate divergent sub-markets.

The month-detrending inside this module is deliberately crude (citywide
monthly median): it only needs to stop clustering from confusing time drift
with location level. The real index is built afterwards on the learned
districts.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest
from philly_fair_measure.models.baseline import RESIDENTIAL_CATEGORIES

logger = logging.getLogger(__name__)

DEFAULT_N_AREAS = 350
DEFAULT_N_DISTRICTS = 18
ASSIGN_NEIGHBORS = 7
# a parcel farther than this (projected metres) from its area's body is a
# disconnected pocket; such a pocket of >= MIN_SPLIT_PARCELS becomes its own
# area, smaller ones merge into the nearest area
CONTIGUITY_RADIUS_M = 300.0
MIN_SPLIT_PARCELS = 50
MIN_PPSF, MAX_PPSF = 10.0, 2000.0
MIN_AREA_SQFT, MAX_AREA_SQFT = 300.0, 10_000.0

# local tangent-plane projection around Philadelphia
_LON0, _LAT0 = -75.16, 39.95
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(_LAT0))
_M_PER_DEG_LAT = 110_540.0


def project_xy(lon: pl.Expr, lat: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    return ((lon - _LON0) * _M_PER_DEG_LON).alias("x_m"), ((lat - _LAT0) * _M_PER_DEG_LAT).alias(
        "y_m"
    )


def sale_points(sales: pl.LazyFrame, opa: pl.LazyFrame) -> pl.DataFrame:
    """Arms-length sales with coordinates and sane $/sqft; shared by this module
    and price_index.py."""
    geo = opa.select(
        pl.col("parcel_number").alias("parcel_id"),
        "lon",
        "lat",
        "lonlat_status",
        pl.col("total_livable_area").alias("livable_area"),
    )
    from philly_fair_measure.config import CONDO_ACCOUNT_PREFIX

    points = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") > 0)
            # condo units carry building-scale areas: poison for $/sqft signals
            & ~pl.col("parcel_id").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
        .select("sale_id", "parcel_id", "sale_date", "sale_price")
        .join(geo, on="parcel_id", how="inner")
        .filter(
            (pl.col("lonlat_status") == "ok")
            & pl.col("livable_area").is_between(MIN_AREA_SQFT, MAX_AREA_SQFT)
        )
        .with_columns((pl.col("sale_price") / pl.col("livable_area")).alias("ppsf"))
        .filter(pl.col("ppsf").is_between(MIN_PPSF, MAX_PPSF))
        .with_columns(
            pl.col("ppsf").log().alias("log_ppsf"),
            pl.col("sale_date").dt.truncate("1mo").alias("month"),
            *project_xy(pl.col("lon"), pl.col("lat")),
        )
        .collect()
    )
    return points


def _detrended(points: pl.DataFrame) -> pl.DataFrame:
    monthly = points.group_by("month").agg(pl.col("log_ppsf").median().alias("month_med"))
    return points.join(monthly, on="month").with_columns(
        (pl.col("log_ppsf") - pl.col("month_med")).alias("adj_log_ppsf")
    )


def _enforce_contiguity(
    assigned: npt.NDArray[np.int64], xy: npt.NDArray[np.float64], n_areas: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Make every area one spatially connected blob. Returns (new labels, parent)
    where parent[final_area] is the original cluster it came from — split-off
    areas inherit their parent's price level and district. Disconnected pockets
    of >= MIN_SPLIT_PARCELS become new areas; smaller strays merge into the
    nearest area (by nearest connected parcel)."""
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    from sklearn.neighbors import radius_neighbors_graph

    def components(idx: npt.NDArray[np.int64]) -> tuple[int, npt.NDArray[np.int64]]:
        graph = radius_neighbors_graph(xy[idx], radius=CONTIGUITY_RADIUS_M, mode="connectivity")
        n_comp, comp = connected_components(graph, directed=False)
        return int(n_comp), np.asarray(comp)

    new = assigned.copy()
    parent = list(range(n_areas))
    next_label = n_areas

    # pass 1: a big disconnected pocket becomes its own area; small strays are
    # merged into the nearest kept parcel's area
    orphan = np.zeros(len(assigned), dtype=bool)
    for area in range(n_areas):
        idx = np.flatnonzero(new == area)
        if len(idx) < 2:
            continue
        n_comp, comp = components(idx)
        if n_comp == 1:
            continue
        sizes = np.bincount(comp)
        keep = int(sizes.argmax())
        for c in range(n_comp):
            if c == keep:
                continue
            members = idx[comp == c]
            if sizes[c] >= MIN_SPLIT_PARCELS:
                new[members] = next_label
                parent.append(area)
                next_label += 1
            else:
                orphan[members] = True
    if orphan.any():
        anchor = ~orphan
        _, nn = cKDTree(xy[anchor]).query(xy[orphan], k=1)
        new[orphan] = new[anchor][np.asarray(nn)]

    # pass 2 (the guarantee): a stray can land farther than the radius and
    # re-split its host area, so split every remaining disconnected component
    # into its own area — a component is contiguous by definition, so nothing
    # survives this
    for area in np.unique(new).tolist():
        idx = np.flatnonzero(new == area)
        if len(idx) < 2:
            continue
        n_comp, comp = components(idx)
        if n_comp == 1:
            continue
        keep = int(np.bincount(comp).argmax())
        for c in range(n_comp):
            if c == keep:
                continue
            new[idx[comp == c]] = next_label
            parent.append(parent[area])  # inherit the ultimate parent cluster
            next_label += 1
    return new, np.asarray(parent, dtype=np.int64)


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_market_areas(
    data_dir: Path | None = None,
    *,
    n_areas: int = DEFAULT_N_AREAS,
    n_districts: int = DEFAULT_N_DISTRICTS,
    seed: int = 42,
) -> BuildResult:
    from scipy.spatial import cKDTree
    from sklearn.cluster import KMeans

    root = data_dir if data_dir is not None else config.data_dir()
    opa_path = root / "staged" / "opa_properties.parquet"
    sales_path = root / "marts" / "sale_validity.parquet"
    for path in (opa_path, sales_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run the pipeline first")

    points = _detrended(sale_points(pl.scan_parquet(sales_path), pl.scan_parquet(opa_path)))
    logger.info("clustering %s sale points into %d market areas", f"{points.height:,}", n_areas)

    features = points.select("x_m", "y_m", "adj_log_ppsf").to_numpy()
    scale = features.std(axis=0)
    scale[scale == 0] = 1.0
    kmeans = KMeans(n_clusters=n_areas, n_init=4, random_state=seed)
    labels = kmeans.fit_predict(features / scale)

    # assign every residential parcel by majority vote of nearest sale points
    parcels = (
        pl.scan_parquet(opa_path)
        .filter(pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES))
        .select(pl.col("parcel_number").alias("parcel_id"), "lon", "lat", "lonlat_status")
        .collect()
        .with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
    )
    located = parcels.filter(pl.col("lonlat_status") == "ok")
    located_xy = located.select("x_m", "y_m").to_numpy()
    tree = cKDTree(points.select("x_m", "y_m").to_numpy())
    _, neighbor_ix = tree.query(located_xy, k=ASSIGN_NEIGHBORS)
    neighbor_labels = labels[neighbor_ix]  # (n_parcels, k)
    assigned = np.asarray(
        [np.bincount(row, minlength=n_areas).argmax() for row in neighbor_labels], dtype=np.int64
    )
    assigned, parent_ix = _enforce_contiguity(assigned, located_xy, n_areas)
    n_areas_final = len(parent_ix)
    logger.info("market areas after contiguity split: %d (was %d)", n_areas_final, n_areas)

    # districts: cluster ORIGINAL area spatial centroids
    points = points.with_columns(pl.Series("area_ix", labels))
    centroids = (
        points.group_by("area_ix").agg(pl.col("x_m").mean(), pl.col("y_m").mean()).sort("area_ix")
    )
    district_of_area = KMeans(n_clusters=n_districts, n_init=4, random_state=seed).fit_predict(
        centroids.select("x_m", "y_m").to_numpy()
    )

    area_stats = (
        points.group_by("area_ix")
        .agg(
            pl.len().cast(pl.Int64).alias("ma_n_sales"),
            pl.col("adj_log_ppsf").median().alias("ma_med_adj_log_ppsf"),
        )
        .sort("area_ix")
        .with_columns(pl.Series("district_ix", district_of_area))
    )
    # expand to the final area set: split-off areas inherit their parent's stats
    final_stats = (
        pl.DataFrame({"area_ix": np.arange(n_areas_final, dtype=np.int64), "parent_ix": parent_ix})
        .join(area_stats.rename({"area_ix": "parent_ix"}), on="parent_ix", how="left")
        .drop("parent_ix")
    )

    def _ma_name(ix: pl.Expr) -> pl.Expr:
        return pl.format("ma_{}", ix.cast(pl.String).str.zfill(3))

    assignments = (
        located.select("parcel_id")
        .with_columns(pl.Series("area_ix", assigned))
        .join(final_stats, on="area_ix", how="left")
        .with_columns(
            _ma_name(pl.col("area_ix")).alias("market_area"),
            pl.format("d_{}", pl.col("district_ix").cast(pl.String).str.zfill(2)).alias("district"),
        )
        .select("parcel_id", "market_area", "district", "ma_n_sales", "ma_med_adj_log_ppsf")
    )
    unlocated = (
        parcels.filter(pl.col("lonlat_status") != "ok")
        .select("parcel_id")
        .with_columns(
            pl.lit(None, dtype=pl.String).alias("market_area"),
            pl.lit(None, dtype=pl.String).alias("district"),
            pl.lit(None, dtype=pl.Int64).alias("ma_n_sales"),
            pl.lit(None, dtype=pl.Float64).alias("ma_med_adj_log_ppsf"),
        )
    )
    frame = pl.concat([assignments, unlocated.select(assignments.columns)])

    inputs = []
    for path in (sales_path, opa_path):
        manifest = read_derived_manifest(path)
        inputs.append(
            InputRef(
                dataset=f"{manifest.layer}/{manifest.table}",
                fetched_at=manifest.built_at.isoformat(),
            )
        )
    path, manifest = write_derived_table(
        frame,
        root,
        "marts",
        "market_areas",
        inputs,
        notes=f"n_areas={n_areas}->{n_areas_final} (contiguity split, "
        f"radius={CONTIGUITY_RADIUS_M}m) n_districts={n_districts} seed={seed} "
        f"assign_neighbors={ASSIGN_NEIGHBORS}",
    )
    return BuildResult(path=path, manifest=manifest)
