"""Model-ready feature table for validated arms-length sales (Milestone 5).

Feature name prefixes encode temporal quality (full registry: docs/features.md):

    char_*  current-state OPA characteristics — current_only. These reflect
            today's roll, not the property as of the sale date; models must
            treat them as leaky for old sales (sensitivity runs with/without).
    mkt_*   market signals from *validated arms-length* prior sales — as_of_sale.
    evt_*   event-dated permit/violation counts strictly before the sale — as_of_sale.
    asmt_*  assessment-roll values for the sale year — before_sale (rolls are
            certified ahead of their year).
    loc_*   location identifiers — quasi-static.
    time_*  sale-date encodings — as_of_sale.

The block-level rolling average adapts CCAO's condo-model insight (leave-one-out,
time-weighted 5-year mean of prior sales among neighbors) to rowhome blocks:
same street_code, same 100-number block, other parcels only, prior sales only,
logistic recency decay. It is the main defense against unobservable interior
condition.
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
    """Leave-one-out, time-weighted rolling mean of prior block sales per sale."""
    p = pool.filter(pl.col("loc_block_id").is_not_null()).select(
        "sale_id", "parcel_id", "loc_block_id", "sale_date", "sale_price"
    )
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
    )
    return pairs.group_by("sale_id").agg(
        ((pl.col("w") * pl.col("sale_price_o")).sum() / pl.col("w").sum()).alias(
            "mkt_block_roll_mean_price"
        ),
        pl.len().alias("mkt_block_roll_n"),
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


def assemble_sale_features(
    sales: pl.LazyFrame,
    opa: pl.LazyFrame,
    permits: pl.LazyFrame,
    violations: pl.LazyFrame,
    assessments: pl.LazyFrame,
    *,
    min_sale_year: int = DEFAULT_MIN_SALE_YEAR,
) -> pl.DataFrame:
    """Pure assembly from staged/mart frames; see module docstring for semantics.

    The full arms-length pool (all years) feeds the rolling windows; the output
    contains only sales from `min_sale_year` onward.
    """
    pool = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") > 0)
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

    pool = pool.join(
        opa_cols.select("parcel_id", "street_code", "house_number_parsed"),
        on="parcel_id",
        how="left",
    ).with_columns(_block_id())

    block_roll = _block_rolling_features(pool)
    parcel_prior = _parcel_prior_sale_features(pool)

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
        .group_by("sale_id")
        .agg(
            ((pl.col("days_before") > 0) & (pl.col("days_before") <= EVENT_WINDOW_DAYS))
            .sum()
            .alias("evt_n_violations_5y_before"),
            (
                pl.col("resolved_date").is_null()
                | (pl.col("resolved_date") > pl.col("sale_date"))
            )
            .sum()
            .alias("evt_n_open_violations_at_sale"),
        )
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
        base.join(opa_cols.drop("street_code", "house_number_parsed"), on="parcel_id", how="left")
        .join(block_roll, on="sale_id", how="left")
        .join(parcel_prior, on="sale_id", how="left")
        .join(permit_feats, on="sale_id", how="left")
        .join(violation_feats, on="sale_id", how="left")
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
        .with_columns(
            pl.col("sale_date").dt.quarter().alias("time_quarter"),
            pl.col("sale_date").dt.month().alias("time_month"),
            pl.col("sale_date").dt.weekday().alias("time_weekday"),
            pl.col("mkt_block_roll_n").fill_null(0),
            pl.col("mkt_parcel_n_prior_sales").fill_null(0),
            pl.col("evt_n_permits_5y_before").fill_null(0),
            pl.col("evt_n_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_violations_at_sale").fill_null(0),
            pl.when(pl.col("asmt_market_value_prev_year") > 0)
            .then(
                pl.col("asmt_market_value_sale_year") / pl.col("asmt_market_value_prev_year")
                - 1.0
            )
            .alias("asmt_value_yoy_change"),
        )
        .drop("asmt_year", "house_number_parsed", strict=False)
    )
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
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing; run `philly stage` and `philly validate-sales` first"
            )

    frame = assemble_sale_features(
        pl.scan_parquet(paths["sale_validity"]),
        pl.scan_parquet(paths["opa_properties"]),
        pl.scan_parquet(paths["permits"]),
        pl.scan_parquet(paths["violations"]),
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
        "sale_features",
        inputs,
        notes=f"arms-length sales {min_sale_year}+; feature registry in docs/features.md",
    )
    return BuildResult(path=path, manifest=manifest)
