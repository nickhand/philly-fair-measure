"""Builders for staged tables: pure LazyFrame -> LazyFrame functions.

Each builder takes the raw snapshot as a LazyFrame so it can be unit-tested on
synthetic frames; the runner wires in real snapshots and writes results.
"""

from __future__ import annotations

import polars as pl

from philly_assessments.staging.geometry import with_point_lonlat
from philly_assessments.staging.temporal import with_parsed_timestamp, with_parsed_year

# Verified against the live rtt_summary table 2026-07-02 (docs/source_inventory.md).
# Spelling varies by system era ("DEED SHERIFF" vs "SHERIFF'S DEED"); one type
# carries a trailing space in the source, so keys are matched on stripped values.
DEED_KIND: dict[str, str] = {
    "DEED": "standard",
    "DEED MISCELLANEOUS": "miscellaneous",
    "MISCELLANEOUS DEED": "miscellaneous",
    "DEED MISCELLANEOUS TAXABLE": "miscellaneous",
    "MISCELLANEOUS DEED TAXABLE": "miscellaneous",
    "DEED SHERIFF": "sheriff",
    "SHERIFF'S DEED": "sheriff",
    "DEED OF CONDEMNATION": "condemnation",
    "DEED LAND BANK": "land_bank",
    "DEED - DECEASED": "deceased",
    "DEED RTT - OTHER": "other",
    "DEED - ADVERSE POSSESSION": "adverse_possession",
}

OPA_TIMESTAMP_COLUMNS = (
    "assessment_date",
    "market_value_date",
    "sale_date",
    "recording_date",
    "date_exterior_condition",
)


def stg_assessments(raw: pl.LazyFrame) -> pl.LazyFrame:
    """Assessment history with typed year, deduplicated on (parcel_number, year).

    41 duplicate keys exist in the source (most with conflicting values); we keep
    the row with the highest cartodb_id (latest inserted) and record how many
    copies each surviving row had (`key_copies`) so ambiguity stays visible.
    """
    lf = with_parsed_year(raw, "year")
    return (
        lf.with_columns(pl.len().over("parcel_number", "year").alias("key_copies"))
        .sort("cartodb_id", descending=True)
        .unique(subset=["parcel_number", "year"], keep="first")
        .select(
            "parcel_number",
            "year",
            "year_parsed",
            "year_status",
            "market_value",
            "taxable_land",
            "taxable_building",
            "exempt_land",
            "exempt_building",
            "key_copies",
            "cartodb_id",
        )
        .sort("parcel_number", "year")
    )


def stg_opa_properties(raw: pl.LazyFrame) -> pl.LazyFrame:
    """Current OPA roll: all raw columns plus parsed temporal columns, year_built,
    lon/lat decoded from the point geometry, and a numeric house number.

    Every value here is current-state only (temporal quality: current_only);
    never treat these characteristics as historically accurate for old sales.
    """
    lf = raw
    for column in OPA_TIMESTAMP_COLUMNS:
        lf = with_parsed_timestamp(lf, column)
    lf = with_parsed_year(lf, "year_built")
    lf = with_point_lonlat(lf)
    return lf.with_columns(
        pl.col("house_number").cast(pl.String).str.strip_chars().cast(pl.Int32, strict=False)
        .alias("house_number_parsed")
    )


def stg_permits(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I permits with parsed event dates, keyed to OPA accounts where linked."""
    lf = raw
    for column in ("permitissuedate", "permitcompleteddate", "certificateofoccupancydate"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "permitnumber",
        "opa_account_num",
        "parcel_id_num",
        "permittype",
        "permitdescription",
        "typeofwork",
        "commercialorresidential",
        "approvedscopeofwork",
        "status",
        "systemofrecord",
        "permitissuedate",
        "permitissuedate_parsed",
        "permitissuedate_status",
        "permitcompleteddate",
        "permitcompleteddate_parsed",
        "permitcompleteddate_status",
        "certificateofoccupancydate",
        "certificateofoccupancydate_parsed",
        "certificateofoccupancydate_status",
        "address",
        "zip",
        "censustract",
        "geocode_x",
        "geocode_y",
    )


def stg_delinquencies(raw: pl.LazyFrame) -> pl.LazyFrame:
    """Real-estate tax delinquencies. CURRENT-ONLY snapshot: the table shows
    today's delinquents, not historical delinquency status — features derived
    from it carry the dist_ (current_only) prefix."""
    lf = with_parsed_timestamp(raw, "most_recent_payment_date")
    return lf.select(
        # opa_number is NUMERIC at the source, destroying the leading zeros of
        # 9-digit OPA accounts; restore them for the string join
        pl.col("opa_number")
        .cast(pl.Int64, strict=False)
        .cast(pl.String)
        .str.zfill(9)
        .alias("opa_account_num"),
        "total_due",
        "principal_due",
        "num_years_owed",
        "oldest_year_owed",
        "most_recent_year_owed",
        "is_actionable",
        "payment_agreement",
        "sheriff_sale",
        "bankruptcy",
        "most_recent_payment_date",
        "most_recent_payment_date_parsed",
        "most_recent_payment_date_status",
        "year_month",
    )


def stg_demolitions(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I demolitions with parsed event dates (true as-of event signal)."""
    lf = raw
    for column in ("start_date", "completed_date"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "caseorpermitnumber",
        "opa_account_num",
        "parcel_id_num",
        "typeofwork",
        "typeofworkdescription",
        "city_demo",
        "status",
        "start_date",
        "start_date_parsed",
        "start_date_status",
        "completed_date",
        "completed_date_parsed",
        "completed_date_status",
        "address",
        "zip",
        "censustract",
        "geocode_x",
        "geocode_y",
    )


def stg_violations(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I violations with parsed event dates, keyed to OPA accounts where linked."""
    lf = raw
    for column in ("violationdate", "violationresolutiondate", "casecreateddate"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "violationnumber",
        "casenumber",
        "opa_account_num",
        "parcel_id_num",
        "violationcode",
        "violationcodetitle",
        "violationstatus",
        "caseprioritydesc",
        "violationdate",
        "violationdate_parsed",
        "violationdate_status",
        "violationresolutiondate",
        "violationresolutiondate_parsed",
        "violationresolutiondate_status",
        "casecreateddate",
        "casecreateddate_parsed",
        "casecreateddate_status",
        "address",
        "zip",
        "censustract",
    )


def stg_deeds(raw: pl.LazyFrame) -> pl.LazyFrame:
    """Deed-family transfer records classified and typed for sales validation.

    Grain: one row per record_id (document x property). Non-deed documents
    (mortgages, satisfactions, ...) are excluded here; nominal or distressed
    deeds are kept and *labeled* downstream, not dropped.
    """
    doc_type = pl.col("document_type").str.strip_chars()
    lf = raw.filter(doc_type.is_in(list(DEED_KIND)))
    lf = lf.with_columns(doc_type.replace_strict(DEED_KIND).alias("deed_kind"))
    for column in ("display_date", "recording_date", "document_date"):
        lf = with_parsed_timestamp(lf, column)
    return lf.with_columns(
        pl.coalesce("display_date_parsed", "document_date_parsed", "recording_date_parsed").alias(
            "sale_date"
        ),
        pl.when(pl.col("display_date_parsed").is_not_null())
        .then(pl.lit("display_date"))
        .when(pl.col("document_date_parsed").is_not_null())
        .then(pl.lit("document_date"))
        .when(pl.col("recording_date_parsed").is_not_null())
        .then(pl.lit("recording_date"))
        .otherwise(pl.lit("none"))
        .alias("sale_date_source"),
        pl.col("total_consideration").alias("sale_price"),
        (pl.col("total_consideration").fill_null(0) <= 1).alias("is_nominal"),
        (pl.col("property_count").fill_null(1) > 1).alias("is_multi_parcel"),
        (
            pl.col("opa_account_num").is_not_null()
            & (pl.col("opa_account_num").str.strip_chars() != "")
        ).alias("has_opa_link"),
    ).select(
        "record_id",
        "document_id",
        "document_type",
        "deed_kind",
        "opa_account_num",
        "has_opa_link",
        "street_address",
        "zip_code",
        "sale_date",
        "sale_date_source",
        "display_date",
        "display_date_parsed",
        "display_date_status",
        "recording_date",
        "recording_date_parsed",
        "recording_date_status",
        "document_date",
        "document_date_parsed",
        "document_date_status",
        "sale_price",
        "is_nominal",
        "cash_consideration",
        "other_consideration",
        "total_consideration",
        "adjusted_total_consideration",
        "fair_market_value",
        "common_level_ratio",
        "property_count",
        "is_multi_parcel",
        "grantors",
        "grantees",
        "condo_name",
        "unit_num",
        "matched_regmap",
        "discrepancy",
    )
