"""Condo sale features (the CCAO condo playbook, adapted to 88-prefix units).

Scope: residential condo units — 88-prefix accounts with residential roll
categories AND "RES CONDO" building codes (32,161 accounts). The 88 prefix
alone is NOT a condo-unit filter: it also covers commercial condos, whole
apartment buildings, parking spaces, vacant declaration land, and
common-element accounts (deliberately assessed nominally — their value lives
in the units).
Sales reach this pool via the staged-deeds condo link recovery
(staging/tables.py): RTT leaves opa_account_num null on most condo unit
deeds, so unlinked deeds are matched to 88 accounts by (address, unit).

Per the CCAO condo design (docs/ccao-lessons.md), the workhorse feature is
the leave-one-out, time-weighted rolling mean of *prior sales in the same
building* — units in a building price together — plus unit characteristics
and the shared market-area/price-index machinery. Condo declarations aren't
public data, so CCAO's %-of-ownership is approximated by the unit's share of
building livable area.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
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
            pl.format("geo_{}_{}", (pl.col("lon") * 1e4).round(0), (pl.col("lat") * 1e4).round(0))
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


def floor_expr() -> pl.Expr:
    """Floor number parsed from the unit token: 2204 -> 22, 8L -> 8, 33K -> 33.

    Tower convention puts the floor in the leading digits (unit 04 on floor 22
    is "2204"); low-rise unit numbers under 100 are read as the floor itself.
    Ambiguities (parking "P209", bare sequence numbers in conversions) land on
    plausible small floors and are accepted as noise — the model weighs the
    signal against them."""
    digits = (
        pl.col("unit")
        .cast(pl.String)
        .str.to_uppercase()
        .str.extract(r"([0-9]{1,4})", 1)
        .cast(pl.Int64, strict=False)
    )
    floor = pl.when(digits >= 100).then(digits // 100).otherwise(digits)
    return pl.when(floor.is_between(1, 70)).then(floor).alias("char_floor")


def condo_units(opa: pl.LazyFrame) -> pl.DataFrame:
    """Residential condo-unit frame shared by the sale mart and the screen.

    Scope: 88-prefix accounts with residential roll categories. The 88 prefix
    alone also covers commercial condos, whole apartment buildings, industrial
    parcels, and parking/storage accounts (measured 2026-07-03 — the v0 pool
    was 85% non-residential before this filter + the deed link recovery).
    Unit-scale area bounds are applied by the callers (the roll rows keep
    whole-building 88 accounts like The Drake at 677k sqft)."""
    from philly_assessments.models.baseline import RESIDENTIAL_CATEGORIES

    units = (
        opa.filter(
            pl.col("parcel_number").str.starts_with(CONDO_ACCOUNT_PREFIX)
            & pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES)
            # the roll's own unit marker: without it, "residential" 88s still
            # include condo parking spaces, vacant declaration land, whole
            # apartment buildings, and common-element accounts (which are
            # deliberately assessed nominally — screening them as
            # "under-assessed" would be wrong on the merits, measured
            # 2026-07-03: unit-less res-88s median 2,550 sqft vs 1,063)
            & pl.col("building_code_description").cast(pl.String).str.starts_with("RES CONDO")
        )
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("location").alias("address"),
            "unit",
            pl.col("category_code_description").alias("char_category"),
            pl.col("market_value").alias("opa_market_value"),
            pl.col("geographic_ward").cast(pl.String).alias("loc_ward"),
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
        .with_columns(building_id_expr(), floor_expr())
    )
    units = with_cluster_building_id(units)
    building_stats = units.group_by("building_id").agg(
        pl.len().alias("bldg_n_units"),
        pl.col("unit_area").sum().alias("_bldg_area"),
    )
    return units.join(building_stats, on="building_id", how="left").with_columns(
        pl.when(pl.col("_bldg_area") > 0)
        .then(pl.col("unit_area") / pl.col("_bldg_area"))
        .alias("unit_area_share")
    )


def assemble_condo_features(
    sales: pl.LazyFrame,
    opa: pl.LazyFrame,
    market_areas: pl.LazyFrame | None = None,
    price_index: pl.DataFrame | None = None,
    assessments: pl.LazyFrame | None = None,
    proximity: pl.LazyFrame | None = None,
    *,
    min_sale_year: int = DEFAULT_MIN_SALE_YEAR,
) -> pl.DataFrame:
    units = condo_units(opa).drop("address", "unit", "opa_market_value", "loc_ward")

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
        # unit-scale areas only: res-coded 88 accounts include whole buildings
        # (The Drake is a "MULTI FAMILY" 88 with 677k sqft and a $233M sale);
        # the ppsf guard drops bulk deeds mislinked to a single unit
        .filter(
            pl.col("unit_area").is_between(250, 12_000)
            & (pl.col("sale_price") / pl.col("unit_area")).is_between(20.0, 5_000.0)
        )
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
    from philly_assessments.features.sale_features import join_proximity

    features = join_proximity(features, proximity)
    return features.sort("sale_date", "sale_id")


def assemble_condo_assessment_features(
    opa: pl.LazyFrame,
    sales: pl.LazyFrame,
    valuation_date: datetime,
    market_areas: pl.LazyFrame | None = None,
    price_index: pl.DataFrame | None = None,
    proximity: pl.LazyFrame | None = None,
) -> pl.DataFrame:
    """Feature table for EVERY residential condo unit at a valuation date.

    The condo analog of features/assessment_features.py: building rolling
    means and the condo kNN surface are computed from arms-length condo sales
    strictly before the valuation date; leave-own-parcel-out is done by
    aggregate subtraction (every unit shares one date). Screened population:
    unit-scale areas (250-12,000 sqft) — parking/storage accounts and
    whole-building 88s are out of model scope."""
    from philly_assessments.features.market_areas import project_xy
    from philly_assessments.features.spatial import knn_ppsf_at_date

    units = condo_units(opa).filter(pl.col("unit_area").is_between(250, 12_000))
    if market_areas is not None:
        areas = market_areas.select(
            "parcel_id", "market_area", "district", "ma_med_adj_log_ppsf"
        ).collect()
        units = units.join(areas, on="parcel_id", how="left").rename(
            {"market_area": "loc_market_area", "district": "loc_district"}
        )
    else:
        units = units.with_columns(
            pl.lit(None, dtype=pl.String).alias("loc_market_area"),
            pl.lit(None, dtype=pl.String).alias("loc_district"),
            pl.lit(None, dtype=pl.Float64).alias("ma_med_adj_log_ppsf"),
        )

    pool = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") >= 25_000)
            & (pl.col("sale_date") <= valuation_date)
            & pl.col("parcel_id").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
        .select("parcel_id", "sale_date", "sale_price")
        .collect()
        .join(
            units.select(
                "parcel_id",
                "building_id",
                "unit_area",
                "loc_district",
                "lon",
                "lat",
                "lonlat_status",
            ),
            on="parcel_id",
            how="inner",
        )
        .filter(
            pl.col("unit_area").is_between(250, 12_000)
            & (pl.col("sale_price") / pl.col("unit_area")).is_between(20.0, 5_000.0)
        )
    )
    if price_index is not None:
        pool = with_time_adjustment(pool, price_index)
        units = with_time_adjustment(
            units.with_columns(pl.lit(valuation_date).alias("_val_date")),
            price_index,
            date_col="_val_date",
        ).drop("_val_date")
    else:
        pool = pool.with_columns(pl.lit(0.0).alias("time_adj_log"))
        units = units.with_columns(pl.lit(0.0).alias("time_adj_log"))

    lo, hi = UNIT_AREA_BOUNDS
    windowed = (
        pool.with_columns(
            (pl.lit(valuation_date) - pl.col("sale_date")).dt.total_days().alias("days_ago")
        )
        .filter(
            (pl.col("days_ago") > 0)
            & (pl.col("days_ago") <= ROLL_WINDOW_DAYS)
            & pl.col("building_id").is_not_null()
        )
        .with_columns(_recency_weight(pl.col("days_ago")).alias("w"))
        .with_columns(
            (pl.col("w") * pl.col("sale_price")).alias("wp"),
            pl.when(pl.col("unit_area").is_between(lo, hi))
            .then(pl.col("w") * (pl.col("sale_price") / pl.col("unit_area")))
            .otherwise(None)
            .alias("wppsf"),
            pl.when(pl.col("unit_area").is_between(lo, hi))
            .then(pl.col("w"))
            .otherwise(0.0)
            .alias("w_ppsf"),
        )
    )
    bldg_totals = windowed.group_by("building_id").agg(
        pl.col("w").sum().alias("bldg_w"),
        pl.col("wp").sum().alias("bldg_wp"),
        pl.col("wppsf").sum().alias("bldg_wppsf"),
        pl.col("w_ppsf").sum().alias("bldg_w_ppsf"),
        pl.len().alias("bldg_n"),
    )
    own_totals = windowed.group_by("building_id", "parcel_id").agg(
        pl.col("w").sum().alias("own_w"),
        pl.col("wp").sum().alias("own_wp"),
        pl.col("wppsf").sum().alias("own_wppsf"),
        pl.col("w_ppsf").sum().alias("own_w_ppsf"),
        pl.len().alias("own_n"),
    )

    knn_points = (
        pool.filter(pl.col("lonlat_status") == "ok")
        .with_columns((pl.col("sale_price") / pl.col("unit_area")).alias("ppsf"))
        .filter(pl.col("ppsf").is_between(20.0, 3000.0))
        .with_columns(
            (pl.col("ppsf").log() + pl.col("time_adj_log")).alias("adj_log_ppsf"),
            *project_xy(pl.col("lon"), pl.col("lat")),
        )
        .select("parcel_id", "x_m", "y_m", "sale_date", "adj_log_ppsf")
    )
    knn_targets = (
        units.filter(pl.col("lonlat_status") == "ok")
        .select("parcel_id", "lon", "lat")
        .with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
        .select("parcel_id", "x_m", "y_m")
    )
    knn = knn_ppsf_at_date(knn_points, knn_targets, valuation_date)

    out = (
        units.join(bldg_totals, on="building_id", how="left")
        .join(own_totals, on=["building_id", "parcel_id"], how="left")
        .with_columns(
            *[
                pl.col(c).fill_null(0.0)
                for c in (
                    "own_w",
                    "own_wp",
                    "own_wppsf",
                    "own_w_ppsf",
                    "bldg_w",
                    "bldg_wp",
                    "bldg_wppsf",
                    "bldg_w_ppsf",
                )
            ],
            pl.col("own_n").fill_null(0),
            pl.col("bldg_n").fill_null(0),
        )
        .with_columns(
            pl.when(pl.col("bldg_w") - pl.col("own_w") > 0)
            .then((pl.col("bldg_wp") - pl.col("own_wp")) / (pl.col("bldg_w") - pl.col("own_w")))
            .alias("mkt_bldg_roll_mean_price"),
            pl.when(pl.col("bldg_w_ppsf") - pl.col("own_w_ppsf") > 0)
            .then(
                (pl.col("bldg_wppsf") - pl.col("own_wppsf"))
                / (pl.col("bldg_w_ppsf") - pl.col("own_w_ppsf"))
            )
            .alias("mkt_bldg_roll_ppsf"),
            (pl.col("bldg_n") - pl.col("own_n")).alias("mkt_bldg_roll_n"),
        )
        .drop(
            "bldg_w",
            "bldg_wp",
            "bldg_wppsf",
            "bldg_w_ppsf",
            "bldg_n",
            "own_w",
            "own_wp",
            "own_wppsf",
            "own_w_ppsf",
            "own_n",
        )
        .join(knn, on="parcel_id", how="left")
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
            pl.lit((valuation_date.month - 1) // 3 + 1).alias("time_quarter"),
            pl.lit(valuation_date.month).alias("time_month"),
        )
        .drop("street_code", "house_number_parsed", "lonlat_status", "_bldg_area", strict=False)
    )
    from philly_assessments.features.sale_features import join_proximity

    return join_proximity(out, proximity)


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
    proximity_path = root / "marts" / "proximity.parquet"
    proximity = None
    if proximity_path.exists():
        paths["proximity"] = proximity_path
        proximity = pl.scan_parquet(proximity_path)
    else:
        logger.warning("marts/proximity.parquet missing; prox_ features will be null")
    frame = assemble_condo_features(
        pl.scan_parquet(paths["sale_validity"]),
        pl.scan_parquet(paths["opa_properties"]),
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
        pl.scan_parquet(paths["assessments"]),
        proximity,
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
