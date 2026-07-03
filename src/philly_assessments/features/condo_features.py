"""Condo sale features (the CCAO condo playbook, adapted to 88-prefix units).

Condos are excluded from the residential model because their reliable
information set is thin; but Philly's units are better-documented than Cook
County's (94% carry unit-scale livable areas, 94% bedrooms). Per the CCAO
condo design (docs/ccao-lessons.md), the workhorse feature is the
leave-one-out, time-weighted rolling mean of *prior sales in the same
building* — units in a building price together — plus unit characteristics
and the shared market-area/price-index machinery.

Building key: street_code + parsed house number (falls back to a rounded
geocode when the house number is missing). Condo declarations aren't public
data, so CCAO's %-of-ownership is approximated by the unit's share of
building livable area.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from philly_assessments import config
from philly_assessments.config import CONDO_ACCOUNT_PREFIX
from philly_assessments.features.price_index import with_time_adjustment
from philly_assessments.features.sale_features import (
    ROLL_WINDOW_DAYS,
    _recency_weight,
    era_expr,
)
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest

logger = logging.getLogger(__name__)

DEFAULT_MIN_SALE_YEAR = 2014
UNIT_AREA_BOUNDS = (150.0, 6_000.0)


def building_id_expr() -> pl.Expr:
    """Stable building key for condo units.

    Geocode-primary (~11m rounding): units in one building share a point, and
    street+number fragments real buildings (address ranges assign different
    house numbers to sibling units — street keys give 9,259 "buildings" with
    69% singletons vs 7,604/56% for the geocode)."""
    return (
        pl.when(pl.col("lonlat_status") == "ok")
        .then(
            pl.format(
                "geo_{}_{}", (pl.col("lon") * 1e4).round(0), (pl.col("lat") * 1e4).round(0)
            )
        )
        .when(pl.col("street_code").is_not_null() & pl.col("house_number_parsed").is_not_null())
        .then(
            pl.concat_str(
                [pl.col("street_code"), pl.col("house_number_parsed").cast(pl.String)],
                separator="_",
            )
        )
        .alias("building_id")
    )


def _building_rolling(pool: pl.DataFrame) -> pl.DataFrame:
    """Leave-one-out time-weighted rolling means of prior sales in the same
    building (the CCAO condo feature). Same-unit prior sales are excluded so
    the feature reflects *neighbors*, not the unit's own history."""
    p = pool.filter(pl.col("building_id").is_not_null()).select(
        "sale_id", "parcel_id", "building_id", "sale_date", "sale_price", "unit_area"
    )
    lo, hi = UNIT_AREA_BOUNDS
    pairs = (
        p.join(p, on="building_id", suffix="_o")
        .filter(
            (pl.col("parcel_id") != pl.col("parcel_id_o"))
            & (pl.col("sale_date") > pl.col("sale_date_o"))
        )
        .with_columns(
            (pl.col("sale_date") - pl.col("sale_date_o")).dt.total_days().alias("days_ago")
        )
        .filter(pl.col("days_ago") <= ROLL_WINDOW_DAYS)
        .with_columns(_recency_weight(pl.col("days_ago")).alias("w"))
        .with_columns(
            pl.when(pl.col("unit_area_o").is_between(lo, hi))
            .then(pl.col("sale_price_o") / pl.col("unit_area_o"))
            .alias("ppsf_o")
        )
    )
    return (
        pairs.group_by("sale_id")
        .agg(
            ((pl.col("w") * pl.col("sale_price_o")).sum() / pl.col("w").sum()).alias(
                "mkt_bldg_roll_mean_price"
            ),
            pl.len().alias("mkt_bldg_roll_n"),
            (pl.col("w") * pl.col("ppsf_o")).sum().alias("_wppsf"),
            pl.when(pl.col("ppsf_o").is_not_null())
            .then(pl.col("w"))
            .otherwise(0.0)
            .sum()
            .alias("_w_ppsf"),
        )
        .with_columns(
            pl.when(pl.col("_w_ppsf") > 0)
            .then(pl.col("_wppsf") / pl.col("_w_ppsf"))
            .alias("mkt_bldg_roll_ppsf")
        )
        .drop("_wppsf", "_w_ppsf")
    )


CLUSTER_RADIUS_M = 30.0


def with_cluster_building_id(units: pl.DataFrame) -> pl.DataFrame:
    """Building key via 30m union-find clustering of unit points.

    Condo units are geocoded at slightly different points *within* a building,
    so coordinate rounding fragments towers, and unit points often fall outside
    PWD parcel polygons (both tried and measured). Connected components over
    30m neighbor pairs recover the building/complex reliably. Even so, the
    measured ceiling is thin: only ~18% of Philly condo sales have a prior
    same-cluster sale within 5 years — Philly is small conversions, not Cook
    County towers — which is why the kNN condo surface, not the building roll,
    is this model's workhorse."""
    import numpy as np
    from scipy.spatial import cKDTree

    from philly_assessments.features.market_areas import project_xy

    located = units["lonlat_status"].fill_null("") == "ok"
    xy = (
        units.with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
        .select("x_m", "y_m")
        .to_numpy()
    )
    xy = np.nan_to_num(xy, nan=1e9)  # unlocated points cluster with nothing
    n = len(xy)
    parent = np.arange(n)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    pairs = cKDTree(xy).query_pairs(CLUSTER_RADIUS_M, output_type="ndarray")
    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    clusters = np.array([find(i) for i in range(n)])
    key = np.where(
        located.to_numpy(),
        np.char.add("bldg_", clusters.astype(str)),
        units["building_id"].fill_null("").to_numpy().astype(str),
    )
    return units.with_columns(pl.Series("building_id", key).replace({"": None}))


def assemble_condo_features(
    sales: pl.LazyFrame,
    opa: pl.LazyFrame,
    market_areas: pl.LazyFrame | None = None,
    price_index: pl.DataFrame | None = None,
    assessments: pl.LazyFrame | None = None,
    *,
    min_sale_year: int = DEFAULT_MIN_SALE_YEAR,
) -> pl.DataFrame:
    units = (
        opa.filter(pl.col("parcel_number").str.starts_with(CONDO_ACCOUNT_PREFIX))
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("total_livable_area").alias("unit_area"),
            pl.col("number_of_bedrooms").alias("char_beds"),
            pl.col("number_of_bathrooms").alias("char_baths"),
            pl.col("year_built_parsed").alias("char_year_built"),
            pl.col("exterior_condition").alias("char_exterior_condition"),
            pl.col("interior_condition").alias("char_interior_condition"),
            pl.col("quality_grade").alias("char_quality_grade_raw"),
            pl.col("zip_code").cast(pl.String).str.slice(0, 5).alias("loc_zip5"),
            "street_code",
            "house_number_parsed",
            "lon",
            "lat",
            "lonlat_status",
        )
        .collect()
        .with_columns(building_id_expr())
    )
    units = with_cluster_building_id(units)
    building_stats = units.group_by("building_id").agg(
        pl.len().alias("bldg_n_units"),
        pl.col("unit_area").sum().alias("_bldg_area"),
    )
    units = units.join(building_stats, on="building_id", how="left").with_columns(
        pl.when(pl.col("_bldg_area") > 0)
        .then(pl.col("unit_area") / pl.col("_bldg_area"))
        .alias("unit_area_share")
    )

    pool = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            # CCAO excludes non-livable condo units (parking, storage, common
            # elements); the public-data analog is tiny areas and token prices
            & (pl.col("sale_price") >= 25_000)
            & pl.col("parcel_id").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
        .select("sale_id", "parcel_id", "sale_date", "sale_price", "sale_year")
        .collect()
        .join(units, on="parcel_id", how="inner")
        .filter(pl.col("unit_area").fill_null(0) >= 250)
    )
    if market_areas is not None:
        areas = market_areas.select(
            "parcel_id", "market_area", "district", "ma_med_adj_log_ppsf"
        ).collect()
        pool = pool.join(areas, on="parcel_id", how="left").rename(
            {"market_area": "loc_market_area", "district": "loc_district"}
        )
    else:
        pool = pool.with_columns(
            pl.lit(None, dtype=pl.String).alias("loc_market_area"),
            pl.lit(None, dtype=pl.String).alias("loc_district"),
            pl.lit(None, dtype=pl.Float64).alias("ma_med_adj_log_ppsf"),
        )
    if price_index is not None:
        pool = with_time_adjustment(pool, price_index)
    else:
        pool = pool.with_columns(pl.lit(0.0).alias("time_adj_log"))

    rolling = _building_rolling(pool)

    # condo-kNN fallback surface: the Philly condo market is thin (12.6k sales
    # across 7.6k buildings), so most units lack recent building history; the
    # nearest prior CONDO sales give every unit a neighborhood condo price level
    from philly_assessments.features.market_areas import project_xy
    from philly_assessments.features.spatial import knn_ppsf_for_sales

    knn_points = (
        pool.filter(pl.col("lonlat_status") == "ok")
        .with_columns((pl.col("sale_price") / pl.col("unit_area")).alias("ppsf"))
        .filter(pl.col("ppsf").is_between(20.0, 3000.0))
        .with_columns(
            (pl.col("ppsf").log() + pl.col("time_adj_log")).alias("adj_log_ppsf"),
            *project_xy(pl.col("lon"), pl.col("lat")),
        )
        .select("sale_id", "parcel_id", "x_m", "y_m", "sale_date", "adj_log_ppsf")
    )
    knn = (
        knn_ppsf_for_sales(knn_points)
        if knn_points.height
        else pl.DataFrame(
            schema={
                "sale_id": pl.String,
                "mkt_knn_log_ppsf": pl.Float64,
                "mkt_knn_n": pl.Int32,
                "mkt_knn_mean_dist_m": pl.Float64,
            }
        )
    )

    base = pool.filter(pl.col("sale_year") >= min_sale_year)
    if assessments is not None:
        asmt = (
            assessments.filter(pl.col("year_parsed").is_not_null())
            .select(
                pl.col("parcel_number").alias("parcel_id"),
                pl.col("year_parsed").alias("asmt_year"),
                pl.col("market_value").alias("asmt_market_value_sale_year"),
            )
            .collect()
        )
        base = base.join(
            asmt,
            left_on=["parcel_id", "sale_year"],
            right_on=["parcel_id", "asmt_year"],
            how="left",
        )
    else:
        base = base.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("asmt_market_value_sale_year")
        )
    features = (
        base.join(rolling, on="sale_id", how="left")
        .join(knn, on="sale_id", how="left")
        .rename(
            {
                "unit_area": "char_unit_area",
                "ma_med_adj_log_ppsf": "mkt_area_level_log_ppsf",
                "lon": "loc_lon",
                "lat": "loc_lat",
            }
        )
        .with_columns(
            era_expr(),
            pl.col("mkt_bldg_roll_n").fill_null(0),
            pl.col("mkt_knn_n").fill_null(0),
            pl.col("sale_date").dt.quarter().alias("time_quarter"),
            pl.col("sale_date").dt.month().alias("time_month"),
        )
        .drop("street_code", "house_number_parsed", "lonlat_status", "_bldg_area", strict=False)
    )
    return features.sort("sale_date", "sale_id")


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_condo_features(
    data_dir: Path | None = None, *, min_sale_year: int = DEFAULT_MIN_SALE_YEAR
) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    paths = {
        "sale_validity": root / "marts" / "sale_validity.parquet",
        "opa_properties": root / "staged" / "opa_properties.parquet",
        "market_areas": root / "marts" / "market_areas.parquet",
        "price_index": root / "marts" / "price_index.parquet",
        "assessments": root / "staged" / "assessments.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run the pipeline first")
    frame = assemble_condo_features(
        pl.scan_parquet(paths["sale_validity"]),
        pl.scan_parquet(paths["opa_properties"]),
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
        pl.scan_parquet(paths["assessments"]),
        min_sale_year=min_sale_year,
    )
    inputs = []
    for path in paths.values():
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
        "condo_sale_features",
        inputs,
        notes=f"arms-length condo sales {min_sale_year}+; CCAO condo playbook",
    )
    return BuildResult(path=path, manifest=manifest)
