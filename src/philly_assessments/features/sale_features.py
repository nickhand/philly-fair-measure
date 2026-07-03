"""Model-ready feature table for validated arms-length sales (Milestone 5 + plan v2).

Feature name prefixes encode temporal quality (full registry: docs/features.md):

    char_*  current-state OPA characteristics — current_only. These reflect
            today's roll, not the property as of the sale date; models must
            treat them as leaky for old sales (sensitivity runs with/without).
    mkt_*   market signals from *validated arms-length* prior sales — as_of_sale.
    evt_*   event-dated permit/violation counts strictly before the sale — as_of_sale.
    asmt_*  assessment-roll values for the sale year — before_sale (rolls are
            certified ahead of their year).
    loc_*   location identifiers — quasi-static (market areas/districts are
            learned from the full sales history: their *boundaries* embed
            all-time information, like OPA's annually redrawn GMAs).
    time_*  sale-date encodings — as_of_sale.

Market signals come in three radii, all leakage-tested (strictly earlier
sales, own parcel excluded):

    block   leave-one-out time-weighted rolling mean on the same street block
            (price level and $/sqft) — CCAO condo-model design;
    kNN     distance-weighted mean time-adjusted $/sqft of the ~15 nearest
            prior sales (features/spatial.py) — OPA's `SPATIAL` analog;
    area    learned market-area price level (features/market_areas.py).

`time_adj_log` carries the district price-index adjustment to the reference
month (features/price_index.py); models may train on adjusted prices
(log price + time_adj_log) and drop time features, per OPA practice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from philly_assessments import config
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest

logger = logging.getLogger(__name__)

ROLL_WINDOW_DAYS = 1825
ROLL_DECAY_YEARS = 3.0
EVENT_WINDOW_DAYS = 1825
DEFAULT_MIN_SALE_YEAR = 2016
PPSF_AREA_BOUNDS = (300.0, 10_000.0)

_CHAR_RENAMES = {
    "total_livable_area": "char_livable_area",
    "total_area": "char_lot_area",
    "frontage": "char_frontage",
    "depth": "char_depth",
    "number_of_bedrooms": "char_beds",
    "number_of_bathrooms": "char_baths",
    "number_of_rooms": "char_rooms",
    "number_stories": "char_stories",
    "year_built_parsed": "char_year_built",
    "exterior_condition": "char_exterior_condition",
    "interior_condition": "char_interior_condition",
    "quality_grade": "char_quality_grade_raw",
    "basements": "char_basement",
    "central_air": "char_central_air",
    "garage_spaces": "char_garage_spaces",
    "fireplaces": "char_fireplaces",
    "type_heater": "char_heater",
    "general_construction": "char_construction",
    "view_type": "char_view",
    "topography": "char_topography",
    "zoning": "char_zoning_raw",
    "building_code_description_new": "char_building_type",
}
_LOC_RENAMES = {
    "census_tract": "loc_census_tract_raw",
    "geographic_ward": "loc_ward",
    "street_code": "loc_street_code",
    "lon": "loc_lon",
    "lat": "loc_lat",
    "lonlat_status": "loc_lonlat_status",
}

SHP_COLUMNS = [
    "shp_parcel_area_m2",
    "shp_parcel_perimeter_m",
    "shp_parcel_num_vertices",
    "shp_parcel_edge_len_sd_m",
    "shp_parcel_interior_angle_sd_deg",
    "shp_parcel_centroid_dist_sd_m",
    "shp_parcel_mrr_area_ratio",
    "shp_parcel_mrr_side_ratio",
    "shp_parcel_num_brt",
    "shp_parcel_num_accounts",
    # owner-linked adjacency (same small owner, touching parcels): the
    # house + side-yard assemblage signal
    "shp_n_linked_parcels",
    "shp_linked_lot_area_m2",
]

# L&I case-priority ladder; everything above STANDARD indicates real distress
SEVERE_PRIORITIES = ["HAZARDOUS", "UNSAFE", "IMMINENTLY DANGEROUS", "UNFIT"]

DIST_COLUMNS = [
    "dist_tax_delinquent",
    "dist_tax_years_owed",
    "dist_tax_total_due",
    "dist_sheriff_sale",
]


def join_delinquencies(frame: pl.DataFrame, delinquencies: pl.LazyFrame | None) -> pl.DataFrame:
    """CURRENT-ONLY distress join (dist_ prefix): the delinquency table shows
    today's delinquents, so these features are honest for recent sales and the
    assessment screen, leaky for old sales — same caveat class as char_."""
    if delinquencies is None:
        return frame.with_columns(
            *[pl.lit(None, dtype=pl.Float64).alias(c) for c in DIST_COLUMNS]
        )
    d = delinquencies.select(
        pl.col("opa_account_num").alias("parcel_id"),
        pl.lit(1.0).alias("dist_tax_delinquent"),
        pl.col("num_years_owed").cast(pl.Float64).alias("dist_tax_years_owed"),
        pl.col("total_due").cast(pl.Float64).alias("dist_tax_total_due"),
        (pl.col("sheriff_sale").cast(pl.String).str.to_uppercase() == "Y")
        .cast(pl.Float64)
        .alias("dist_sheriff_sale"),
    ).collect()
    return frame.join(d, on="parcel_id", how="left").with_columns(
        pl.col("dist_tax_delinquent").fill_null(0.0),
        pl.col("dist_sheriff_sale").fill_null(0.0),
    )


def join_parcel_shapes(frame: pl.DataFrame, parcels: pl.LazyFrame | None) -> pl.DataFrame:
    """Attach shp_* columns by OPA account; null columns when parcels are absent
    so the model feature set is stable either way."""
    if parcels is None:
        return frame.with_columns(
            *[pl.lit(None, dtype=pl.Float64).alias(c) for c in SHP_COLUMNS]
        )
    shp = parcels.select(
        pl.col("brt_id").alias("parcel_id"),
        pl.col("num_brt").cast(pl.Float64).alias("shp_parcel_num_brt"),
        pl.col("num_accounts").cast(pl.Float64).alias("shp_parcel_num_accounts"),
        *[c for c in SHP_COLUMNS if not c.endswith(("_num_brt", "_num_accounts"))],
    ).collect()
    return frame.join(shp, on="parcel_id", how="left")

# standalone (non-ROW/TWIN) style names observed in building_code_description_new
_DETACHED_STYLES = [
    "CONVENTIONAL", "CAPE", "COLONIAL", "SPLIT LEVEL", "RANCH", "RANCHER",
    "BUNGALOW", "TUDOR", "VICTORIAN", "CONTEMPORARY",
]


def style_expr(source: str = "char_building_type") -> pl.Expr:
    bt = pl.col(source).cast(pl.String).str.strip_chars()
    return (
        pl.when(bt.is_null())
        .then(pl.lit("unknown"))
        .when(bt.str.starts_with("ROW"))
        .then(pl.lit("row"))
        .when(bt.str.starts_with("TWIN") | bt.str.starts_with("SEMI"))
        .then(pl.lit("twin"))
        .when(bt.str.starts_with("DET") | bt.is_in(_DETACHED_STYLES))
        .then(pl.lit("detached"))
        .otherwise(pl.lit("other"))
        .alias("char_style")
    )


def era_expr(source: str = "char_year_built") -> pl.Expr:
    y = pl.col(source)
    return (
        pl.when(y.is_null())
        .then(pl.lit("unknown"))
        .when(y < 1900)
        .then(pl.lit("pre1900"))
        .when(y < 1920)
        .then(pl.lit("1900s"))
        .when(y < 1940)
        .then(pl.lit("1920s_30s"))
        .when(y < 1960)
        .then(pl.lit("1940s_50s"))
        .when(y < 1980)
        .then(pl.lit("1960s_70s"))
        .when(y < 2000)
        .then(pl.lit("1980s_90s"))
        .when(y < 2010)
        .then(pl.lit("2000s"))
        .otherwise(pl.lit("2010plus"))
        .alias("char_era")
    )


def _block_id() -> pl.Expr:
    block_number = (pl.col("house_number_parsed") // 100) * 100
    return (
        pl.when(pl.col("street_code").is_not_null() & block_number.is_not_null())
        .then(
            pl.concat_str(
                [pl.col("street_code"), block_number.cast(pl.String)], separator="_"
            )
        )
        .alias("loc_block_id")
    )


def _recency_weight(days: pl.Expr) -> pl.Expr:
    """Logistic decay per CCAO's condo model: ~0.95 at 0y, 0.5 at 3y, ~0.12 at 5y."""
    return 1.0 / (1.0 + ((days / 365.25) - ROLL_DECAY_YEARS).exp())


def _block_rolling_features(pool: pl.DataFrame) -> pl.DataFrame:
    """Leave-one-out, time-weighted rolling means (price level and $/sqft) of
    prior block sales per sale."""
    p = pool.filter(pl.col("loc_block_id").is_not_null()).select(
        "sale_id", "parcel_id", "loc_block_id", "sale_date", "sale_price", "livable_area"
    )
    lo, hi = PPSF_AREA_BOUNDS
    pairs = (
        p.join(p, on="loc_block_id", suffix="_o")
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
            pl.when(pl.col("livable_area_o").is_between(lo, hi))
            .then(pl.col("sale_price_o") / pl.col("livable_area_o"))
            .alias("ppsf_o")
        )
    )
    return (
        pairs.group_by("sale_id")
        .agg(
            ((pl.col("w") * pl.col("sale_price_o")).sum() / pl.col("w").sum()).alias(
                "mkt_block_roll_mean_price"
            ),
            pl.len().alias("mkt_block_roll_n"),
            (pl.col("w") * pl.col("ppsf_o")).sum().alias("_wppsf"),
            pl.when(pl.col("ppsf_o").is_not_null())
            .then(pl.col("w"))
            .otherwise(0.0)
            .sum()
            .alias("_w_ppsf"),
        )
        .with_columns(
            # guard 0/0: peers may all lack a valid livable area
            pl.when(pl.col("_w_ppsf") > 0)
            .then(pl.col("_wppsf") / pl.col("_w_ppsf"))
            .alias("mkt_block_roll_ppsf")
        )
        .drop("_wppsf", "_w_ppsf")
    )


def _parcel_prior_sale_features(pool: pl.DataFrame) -> pl.DataFrame:
    p = pool.select("sale_id", "parcel_id", "sale_date", "sale_price")
    pairs = p.join(p, on="parcel_id", suffix="_o").filter(
        pl.col("sale_date") > pl.col("sale_date_o")
    )
    return pairs.group_by("sale_id").agg(
        pl.len().alias("mkt_parcel_n_prior_sales"),
        (pl.col("sale_date") - pl.col("sale_date_o"))
        .dt.total_days()
        .min()
        .alias("mkt_parcel_days_since_prev"),
        pl.col("sale_price_o").sort_by("sale_date_o").last().alias("mkt_parcel_prev_price"),
    )


def _knn_surface(pool: pl.DataFrame) -> pl.DataFrame:
    """As-of kNN $/sqft surface for every pooled sale (see features/spatial.py)."""
    from philly_assessments.features.market_areas import project_xy
    from philly_assessments.features.spatial import knn_ppsf_for_sales

    lo, hi = PPSF_AREA_BOUNDS
    points = (
        pool.filter(
            (pl.col("lonlat_status") == "ok")
            & pl.col("livable_area").is_between(lo, hi)
        )
        .with_columns((pl.col("sale_price") / pl.col("livable_area")).alias("ppsf"))
        .filter(pl.col("ppsf").is_between(10.0, 2000.0))
        .with_columns(
            (pl.col("ppsf").log() + pl.col("time_adj_log")).alias("adj_log_ppsf"),
            *project_xy(pl.col("lon"), pl.col("lat")),
        )
        .select("sale_id", "parcel_id", "x_m", "y_m", "sale_date", "adj_log_ppsf")
    )
    if points.height == 0:
        return pl.DataFrame(
            schema={
                "sale_id": pl.String,
                "mkt_knn_log_ppsf": pl.Float64,
                "mkt_knn_n": pl.Int32,
                "mkt_knn_mean_dist_m": pl.Float64,
            }
        )
    return knn_ppsf_for_sales(points)


def assemble_sale_features(
    sales: pl.LazyFrame,
    opa: pl.LazyFrame,
    permits: pl.LazyFrame,
    violations: pl.LazyFrame,
    assessments: pl.LazyFrame,
    market_areas: pl.LazyFrame | None = None,
    price_index: pl.DataFrame | None = None,
    parcels: pl.LazyFrame | None = None,
    demolitions: pl.LazyFrame | None = None,
    delinquencies: pl.LazyFrame | None = None,
    *,
    min_sale_year: int = DEFAULT_MIN_SALE_YEAR,
) -> pl.DataFrame:
    """Pure assembly from staged/mart frames; see module docstring for semantics.

    The full arms-length pool (all years) feeds the rolling windows; the output
    contains only sales from `min_sale_year` onward. `market_areas` and
    `price_index` are optional so unit tests can run without them: without an
    index every `time_adj_log` is 0.0; without market areas the loc_market_area
    columns are null.
    """
    from philly_assessments.config import CONDO_ACCOUNT_PREFIX
    from philly_assessments.features.price_index import with_time_adjustment

    pool = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") > 0)
            # 88-prefix = condo units: excluded from the residential scope AND
            # from the market-signal pools (their building-scale areas corrupt
            # $/sqft rolls and the kNN surface)
            & ~pl.col("parcel_id").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
        .select(
            "sale_id",
            "parcel_id",
            "sale_date",
            "sale_price",
            "sale_year",
            "zip5",
            "category_code_description",
        )
        .collect()
    )
    opa_cols = opa.select(
        pl.col("parcel_number").alias("parcel_id"),
        "street_code",
        "house_number_parsed",
        *_CHAR_RENAMES,
        *[c for c in _LOC_RENAMES if c != "street_code"],
    ).collect()

    area_cols = ["parcel_id", "market_area", "district", "ma_med_adj_log_ppsf"]
    if market_areas is not None:
        areas = market_areas.select(area_cols).collect()
    else:
        areas = pl.DataFrame(
            schema={
                "parcel_id": pl.String,
                "market_area": pl.String,
                "district": pl.String,
                "ma_med_adj_log_ppsf": pl.Float64,
            }
        )

    pool = (
        pool.join(
            opa_cols.select(
                "parcel_id",
                "street_code",
                "house_number_parsed",
                pl.col("total_livable_area").alias("livable_area"),
                "lon",
                "lat",
                "lonlat_status",
            ),
            on="parcel_id",
            how="left",
        )
        .with_columns(_block_id())
        .join(areas, on="parcel_id", how="left")
        .rename({"market_area": "loc_market_area", "district": "loc_district"})
    )
    if price_index is not None:
        pool = with_time_adjustment(pool, price_index)
    else:
        pool = pool.with_columns(pl.lit(0.0).alias("time_adj_log"))

    block_roll = _block_rolling_features(pool)
    parcel_prior = _parcel_prior_sale_features(pool)
    knn = _knn_surface(pool)

    base = pool.filter(pl.col("sale_year") >= min_sale_year)

    permit_events = (
        permits.filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("permitissuedate_parsed").is_not_null()
        )
        .select(
            pl.col("opa_account_num").alias("parcel_id"),
            pl.col("permitissuedate_parsed").alias("event_date"),
        )
        .collect()
    )
    permit_feats = (
        base.select("sale_id", "parcel_id", "sale_date")
        .join(permit_events, on="parcel_id")
        .with_columns(
            (pl.col("sale_date") - pl.col("event_date")).dt.total_days().alias("days_before")
        )
        .filter(pl.col("days_before") > 0)
        .group_by("sale_id")
        .agg(
            (pl.col("days_before") <= EVENT_WINDOW_DAYS).sum().alias("evt_n_permits_5y_before"),
            pl.col("days_before").min().alias("evt_days_since_last_permit"),
        )
    )

    violation_events = (
        violations.filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("violationdate_parsed").is_not_null()
        )
        .select(
            pl.col("opa_account_num").alias("parcel_id"),
            pl.col("violationdate_parsed").alias("event_date"),
            pl.col("violationresolutiondate_parsed").alias("resolved_date"),
            pl.col("caseprioritydesc")
            .cast(pl.String)
            .is_in(SEVERE_PRIORITIES)
            .fill_null(False)
            .alias("is_severe"),
        )
        .collect()
    )
    violation_feats = (
        base.select("sale_id", "parcel_id", "sale_date")
        .join(violation_events, on="parcel_id")
        .with_columns(
            (pl.col("sale_date") - pl.col("event_date")).dt.total_days().alias("days_before")
        )
        .filter(pl.col("days_before") >= 0)
        .with_columns(
            ((pl.col("days_before") > 0) & (pl.col("days_before") <= EVENT_WINDOW_DAYS))
            .alias("in_window"),
            (
                pl.col("resolved_date").is_null()
                | (pl.col("resolved_date") > pl.col("sale_date"))
            ).alias("is_open"),
        )
        .group_by("sale_id")
        .agg(
            pl.col("in_window").sum().alias("evt_n_violations_5y_before"),
            pl.col("is_open").sum().alias("evt_n_open_violations_at_sale"),
            (pl.col("in_window") & pl.col("is_severe"))
            .sum()
            .alias("evt_n_severe_violations_5y_before"),
            (pl.col("is_open") & pl.col("is_severe"))
            .sum()
            .alias("evt_n_open_severe_at_sale"),
        )
    )

    if demolitions is not None:
        demo_events = (
            demolitions.filter(
                pl.col("opa_account_num").is_not_null()
                & pl.coalesce("completed_date_parsed", "start_date_parsed").is_not_null()
            )
            .select(
                pl.col("opa_account_num").alias("parcel_id"),
                pl.coalesce("completed_date_parsed", "start_date_parsed").alias("event_date"),
            )
            .collect()
        )
        demo_feats = (
            base.select("sale_id", "parcel_id", "sale_date")
            .join(demo_events, on="parcel_id")
            .with_columns(
                (pl.col("sale_date") - pl.col("event_date")).dt.total_days().alias("days_before")
            )
            .filter(pl.col("days_before") > 0)
            .group_by("sale_id")
            .agg(
                pl.len().alias("evt_n_demolitions_before"),
                pl.col("days_before").min().alias("evt_demo_days_since"),
            )
        )
    else:
        demo_feats = pl.DataFrame(
            schema={
                "sale_id": pl.String,
                "evt_n_demolitions_before": pl.UInt32,
                "evt_demo_days_since": pl.Int64,
            }
        )

    asmt = (
        assessments.filter(pl.col("year_parsed").is_not_null())
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("year_parsed").alias("asmt_year"),
            pl.col("market_value").alias("asmt_market_value"),
        )
        .collect()
    )
    current_asmt = asmt.rename({"asmt_market_value": "asmt_market_value_sale_year"})
    prior_asmt = asmt.rename({"asmt_market_value": "asmt_market_value_prev_year"})

    features = (
        # lon/lat/livable_area were pool-side helpers; the canonical copies come
        # from the opa_cols join below
        base.drop("lon", "lat", "lonlat_status", "livable_area")
        .join(
            opa_cols.drop("street_code", "house_number_parsed"), on="parcel_id", how="left"
        )
        .join(block_roll, on="sale_id", how="left")
        .join(parcel_prior, on="sale_id", how="left")
        .join(knn, on="sale_id", how="left")
        .join(permit_feats, on="sale_id", how="left")
        .join(violation_feats, on="sale_id", how="left")
        .join(demo_feats, on="sale_id", how="left")
        .join(
            current_asmt,
            left_on=["parcel_id", "sale_year"],
            right_on=["parcel_id", "asmt_year"],
            how="left",
        )
        .join(
            prior_asmt.with_columns((pl.col("asmt_year") + 1).alias("join_year")),
            left_on=["parcel_id", "sale_year"],
            right_on=["parcel_id", "join_year"],
            how="left",
        )
        .rename({**_CHAR_RENAMES, **_LOC_RENAMES})
        .rename({"zip5": "loc_zip5", "category_code_description": "char_category"})
        .rename({"ma_med_adj_log_ppsf": "mkt_area_level_log_ppsf"})
        .with_columns(
            style_expr(),
            era_expr(),
            pl.col("sale_date").dt.quarter().alias("time_quarter"),
            pl.col("sale_date").dt.month().alias("time_month"),
            pl.col("sale_date").dt.weekday().alias("time_weekday"),
            pl.col("mkt_block_roll_n").fill_null(0),
            pl.col("mkt_knn_n").fill_null(0),
            pl.col("mkt_parcel_n_prior_sales").fill_null(0),
            pl.col("evt_n_permits_5y_before").fill_null(0),
            pl.col("evt_n_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_violations_at_sale").fill_null(0),
            pl.col("evt_n_severe_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_severe_at_sale").fill_null(0),
            pl.col("evt_n_demolitions_before").fill_null(0),
            pl.when(pl.col("asmt_market_value_prev_year") > 0)
            .then(
                pl.col("asmt_market_value_sale_year") / pl.col("asmt_market_value_prev_year")
                - 1.0
            )
            .alias("asmt_value_yoy_change"),
        )
        .drop("asmt_year", "house_number_parsed", "livable_area", strict=False)
    )
    features = join_parcel_shapes(features, parcels)
    features = join_delinquencies(features, delinquencies)
    return features.sort("sale_date", "sale_id")


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_sale_features(
    data_dir: Path | None = None, *, min_sale_year: int = DEFAULT_MIN_SALE_YEAR
) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    paths = {
        "sale_validity": root / "marts" / "sale_validity.parquet",
        "opa_properties": root / "staged" / "opa_properties.parquet",
        "permits": root / "staged" / "permits.parquet",
        "violations": root / "staged" / "violations.parquet",
        "assessments": root / "staged" / "assessments.parquet",
        "market_areas": root / "marts" / "market_areas.parquet",
        "price_index": root / "marts" / "price_index.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing; run snapshots, `philly stage`, `philly validate-sales`, "
                "`philly build-market-areas`, and `philly build-price-index` first"
            )
    optional = {}
    for name in ("parcels", "demolitions", "delinquencies"):
        path = root / "staged" / f"{name}.parquet"
        if path.exists():
            paths[name] = path
            optional[name] = pl.scan_parquet(path)
        else:
            optional[name] = None
            logger.warning("staged %s missing; its features will be null", name)

    frame = assemble_sale_features(
        pl.scan_parquet(paths["sale_validity"]),
        pl.scan_parquet(paths["opa_properties"]),
        pl.scan_parquet(paths["permits"]),
        pl.scan_parquet(paths["violations"]),
        pl.scan_parquet(paths["assessments"]),
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
        optional["parcels"],
        optional["demolitions"],
        optional["delinquencies"],
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
        "sale_features",
        inputs,
        notes=f"arms-length sales {min_sale_year}+; feature registry in docs/features.md",
    )
    return BuildResult(path=path, manifest=manifest)
