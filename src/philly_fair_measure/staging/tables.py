"""Builders for staged tables: pure LazyFrame -> LazyFrame functions.

Each builder takes the raw snapshot as a LazyFrame so it can be unit-tested on
synthetic frames; the runner wires in real snapshots and writes results.
"""

from __future__ import annotations

import polars as pl

from philly_fair_measure.staging.geometry import with_point_lonlat
from philly_fair_measure.staging.temporal import with_parsed_timestamp, with_parsed_year
from philly_fair_measure.vocab import OpaLinkSource

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
        pl.col("house_number")
        .cast(pl.String)
        .str.strip_chars()
        .cast(pl.Int32, strict=False)
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
        # 9-digit OPA accounts; restore them for the string join. A source 0
        # means "no account", not account 000000000 — null it so the key can
        # never fan out a join
        pl.when(pl.col("opa_number").cast(pl.Int64, strict=False) > 0)
        .then(pl.col("opa_number").cast(pl.Int64, strict=False).cast(pl.String).str.zfill(9))
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


def stg_complaints(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I complaints: resident-initiated reports with true event dates.

    The upstream of violations — the closest public proxy for interior
    condition (MAINTENANCE RESIDENTIAL is tenants reporting heat/plumbing/
    electrical) and the city's only live vacancy feed (VACANT HOUSE)."""
    lf = raw
    for column in ("complaintdate", "complaintresolution_date"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "complaintnumber",
        "casenumber",
        "opa_account_num",
        "parcel_id_num",
        "complaintcode",
        "complaintcodename",
        "complaintstatus",
        "casestatus",
        "unitresponsible",
        "complaintdate",
        "complaintdate_parsed",
        "complaintdate_status",
        "complaintresolution_date",
        "complaintresolution_date_parsed",
        "complaintresolution_date_status",
        "address",
        "zip",
        "censustract",
    )


def stg_case_investigations(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I case investigations (inspection events), keyed to OPA accounts.

    Adds the escalation ladder beyond violations: PRECOURT investigations mark
    cases headed to court (severe, prolonged distress); HCEU INSP are housing
    code enforcement inspections (interior access happened)."""
    lf = with_parsed_timestamp(raw, "investigationcompleted")
    return lf.select(
        "casenumber",
        "opa_account_num",
        "parcel_id_num",
        "casetype",
        "casepriority",
        "investigationtype",
        "investigationstatus",
        "investigationcompleted",
        "investigationcompleted_parsed",
        "investigationcompleted_status",
        "address",
        "zip",
        "censustract",
    )


def stg_rental_licenses(raw: pl.LazyFrame) -> pl.LazyFrame:
    """Rental business licenses: per-parcel tenure spans.

    A license active at a sale date marks the property investor-/landlord-held
    as of that sale (initialissuedate <= date < inactivedate). owneroccupied
    and numberofunits come straight from the license record."""
    lf = raw.filter(pl.col("licensetype").cast(pl.String) == "Rental")
    for column in ("initialissuedate", "mostrecentissuedate", "expirationdate", "inactivedate"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "licensenum",
        "opa_account_num",
        "parcel_id_num",
        "rentalcategory",
        "licensestatus",
        "owneroccupied",
        "numberofunits",
        "initialissuedate",
        "initialissuedate_parsed",
        "initialissuedate_status",
        "mostrecentissuedate",
        "mostrecentissuedate_parsed",
        "mostrecentissuedate_status",
        "expirationdate",
        "expirationdate_parsed",
        "expirationdate_status",
        "inactivedate",
        "inactivedate_parsed",
        "inactivedate_status",
        "address",
        "zip",
        "censustract",
    )


def stg_appeals(raw: pl.LazyFrame) -> pl.LazyFrame:
    """L&I / ZBA appeals with decisions.

    A granted ZBA variance is a development entitlement the characteristics
    table won't show for years — an uplift event with a true decision date."""
    lf = raw
    for column in ("createddate", "scheduleddate", "decisiondate", "completeddate"):
        lf = with_parsed_timestamp(lf, column)
    return lf.select(
        "appealnumber",
        "opa_account_num",
        "parcel_id_num",
        "appealtype",
        "applicationtype",
        "appealstatus",
        "appealgrounds",
        "decision",
        "meetingresult",
        "relatedpermit",
        "createddate",
        "createddate_parsed",
        "createddate_status",
        "scheduleddate",
        "scheduleddate_parsed",
        "scheduleddate_status",
        "decisiondate",
        "decisiondate_parsed",
        "decisiondate_status",
        "completeddate",
        "completeddate_parsed",
        "completeddate_status",
        "address",
        "zip",
        "censustract",
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


_UNIT_TOKEN_REGEX = r"\b(?:APT|UNIT|STE|SUITE|PH|FL|#)\s*([0-9A-Z-]+)$"
_UNIT_SUFFIX_REGEX = r"\s+(?:APT|UNIT|STE|SUITE|PH|FL|#)\s*[0-9A-Z-]*$"


def _norm_unit(expr: pl.Expr) -> pl.Expr:
    return (
        expr.cast(pl.String)
        .str.to_uppercase()
        .str.replace_all(r"[^0-9A-Z]", "")
        .str.strip_chars_start("0")
    )


def _norm_address(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.String).str.to_uppercase().str.replace_all(r"\s+", " ").str.strip_chars()


def _condo_unit_lookup(raw_opa: pl.LazyFrame) -> pl.LazyFrame:
    """(normalized address, unit) -> 88-prefix account, unique keys only."""
    from philly_fair_measure.config import CONDO_ACCOUNT_PREFIX

    keyed = (
        raw_opa.filter(
            pl.col("parcel_number").cast(pl.String).str.starts_with(CONDO_ACCOUNT_PREFIX)
            & pl.col("unit").is_not_null()
        )
        .select(
            pl.col("parcel_number").cast(pl.String).alias("recovered_opa_account"),
            _norm_address(pl.col("location")).alias("_match_base"),
            _norm_unit(pl.col("unit")).alias("_match_unit"),
        )
        .filter(pl.col("_match_unit") != "")
    )
    return keyed.filter(pl.len().over("_match_base", "_match_unit") == 1)


def stg_deeds(raw: pl.LazyFrame, raw_opa: pl.LazyFrame | None = None) -> pl.LazyFrame:
    """Deed-family transfer records classified and typed for sales validation.

    Grain: one row per record_id (document x property). Non-deed documents
    (mortgages, satisfactions, ...) are excluded here; nominal or distressed
    deeds are kept and *labeled* downstream, not dropped.

    Condo link recovery: RTT leaves `opa_account_num` null on most condo unit
    deeds (measured 2026-07-03: 0% of Academy House / Symphony House resales
    carried a link), which silently removed condos from every sale pool. When
    `raw_opa` is given, unlinked deeds are matched to 88-prefix accounts on
    (normalized street address, normalized unit token) — unit from RTT's
    `unit_num`, falling back to an APT/UNIT suffix in `street_address` —
    accepting only unique (address, unit) keys. Recovered rows get
    `opa_link_source = "address_unit"`; native links are `"rtt"`.
    """
    doc_type = pl.col("document_type").str.strip_chars()
    lf = raw.filter(doc_type.is_in(list(DEED_KIND)))
    lf = lf.with_columns(doc_type.replace_strict(DEED_KIND).alias("deed_kind"))
    for column in ("display_date", "recording_date", "document_date"):
        lf = with_parsed_timestamp(lf, column)
    lf = lf.with_columns(
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
    return _with_condo_recovered_links(lf, raw_opa)


def _with_condo_recovered_links(lf: pl.LazyFrame, raw_opa: pl.LazyFrame | None) -> pl.LazyFrame:
    """Fill null opa_account_num on RTT rows by (address, unit) matching to
    88-prefix accounts; shared by stg_deeds and stg_mortgages."""
    if raw_opa is None:
        return lf.with_columns(
            pl.when(pl.col("has_opa_link")).then(pl.lit(OpaLinkSource.RTT)).alias("opa_link_source")
        )
    lf = lf.with_columns(
        _norm_address(pl.col("street_address").str.replace(_UNIT_SUFFIX_REGEX, "")).alias(
            "_match_base"
        ),
        pl.coalesce(
            _norm_unit(pl.col("unit_num")),
            _norm_unit(pl.col("street_address").str.extract(_UNIT_TOKEN_REGEX, 1)),
        ).alias("_match_unit"),
    ).join(_condo_unit_lookup(raw_opa), on=["_match_base", "_match_unit"], how="left")
    recovered = ~pl.col("has_opa_link") & pl.col("recovered_opa_account").is_not_null()
    return lf.with_columns(
        pl.when(recovered)
        .then(pl.col("recovered_opa_account"))
        .otherwise(pl.col("opa_account_num"))
        .alias("opa_account_num"),
        pl.when(pl.col("has_opa_link"))
        .then(pl.lit(OpaLinkSource.RTT))
        .when(recovered)
        .then(pl.lit(OpaLinkSource.ADDRESS_UNIT))
        .alias("opa_link_source"),
        (pl.col("has_opa_link") | recovered).alias("has_opa_link"),
    ).drop("_match_base", "_match_unit", "recovered_opa_account")


# Hard-money / fix-and-flip lender tokens, matched against the mortgage
# grantee (lender) name. Curated from national flip lenders + measured hits
# in the live RTT snapshot (2026-07-03: KIAVI 1,612, LIMA ONE 1,299,
# RCN 812, DOMINION 485, LENDINGONE 473, CIVIC 443, TVC 323...). A mortgage
# from one of these is a near-certain renovation-in-progress signal —
# including work that never pulls an L&I permit.
HARD_MONEY_TOKENS = [
    "KIAVI",
    "LENDINGHOME",  # Kiavi's former name
    "LIMA ONE",
    "RCN CAPITAL",
    "CIVIC FINANCIAL",
    "ANCHOR LOANS",
    "DOMINION FINANCIAL",
    "LENDINGONE",
    "TVC FUNDING",
    "TEMPLE VIEW CAPITAL",
    "ROC CAPITAL",
    "TOORAK",
    "FUND THAT FLIP",
    "SHERMAN BRIDGE",
    "VISIO FINANCIAL",
    "CONSTRUCTIVE LOANS",
    "EASY STREET CAPITAL",
]
_HARD_MONEY_REGEX = "|".join(HARD_MONEY_TOKENS)


def stg_mortgages(raw: pl.LazyFrame, raw_opa: pl.LazyFrame | None = None) -> pl.LazyFrame:
    """MORTGAGE documents from RTT: financing events per parcel.

    Loan amounts are NOT recorded (transfer tax doesn't apply to mortgages;
    all consideration fields are ~empty — measured 2026-07-03), so the signal
    is presence, timing, and lender identity: cash-vs-financed purchases,
    refinances after purchase (capital injections), and hard-money lenders
    (renovation nearly certain). 85% carry native OPA links; condo link
    recovery fills unit-level gaps like stg_deeds."""
    lf = raw.filter(pl.col("document_type").str.strip_chars() == "MORTGAGE")
    for column in ("display_date", "recording_date", "document_date"):
        lf = with_parsed_timestamp(lf, column)
    lf = lf.with_columns(
        pl.coalesce("display_date_parsed", "document_date_parsed", "recording_date_parsed").alias(
            "mortgage_date"
        ),
        (
            pl.col("opa_account_num").is_not_null()
            & (pl.col("opa_account_num").str.strip_chars() != "")
        ).alias("has_opa_link"),
        pl.col("grantees")
        .cast(pl.String)
        .str.to_uppercase()
        .str.contains(_HARD_MONEY_REGEX)
        .fill_null(False)
        .alias("is_hard_money"),
    ).select(
        "record_id",
        "document_id",
        "opa_account_num",
        "has_opa_link",
        "street_address",
        "unit_num",
        "mortgage_date",
        "grantors",
        "grantees",
        "is_hard_money",
        "property_count",
    )
    return _with_condo_recovered_links(lf, raw_opa)
