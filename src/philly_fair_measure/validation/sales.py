"""Sale-validity classification, adapted from the CCAO sales-validation approach
(see docs/ccao-lessons.md).

Every deed gets a `validity_status` plus explainable `validity_reasons`:

    arms_length      no disqualifying evidence
    suspect          priced sale with outlier/heuristic evidence against it
    nominal          consideration <= $1 (family transfers, corrective deeds, ...)
    not_arms_length  deed kind implies a non-market transfer (sheriff, land bank, ...)
    excluded         cannot be validated (multi-parcel, no OPA link, no date,
                     duplicate price within a year)

Following CCAO practice, only price evidence and deed kind drive the status;
name-based heuristics (legal-entity buyer/seller, possible related parties) are
recorded as supplementary flags/reasons but never flip the status by themselves.

Group outlier detection: z-scores of log(price) and price-per-sqft within
(zip5, property category, sale year) groups with at least MIN_GROUP_SIZE
eligible sales. 88-prefix condo units pool separately as "CONDO UNIT"
regardless of their roll category — their $/sqft distribution would otherwise
distort the SINGLE FAMILY reference pools in condo-heavy zips (and vice
versa). Livable area is current-state only, so the price-per-sqft screen
inherits that temporal caveat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from philly_fair_measure import __version__, config
from philly_fair_measure.ingest.manifests import (
    DerivedManifest,
    InputRef,
    read_derived_manifest,
    write_derived_manifest,
)
from philly_fair_measure.vocab import ValidityStatus

logger = logging.getLogger(__name__)

MIN_GROUP_SIZE = 20
Z_THRESHOLD = 3.0
LOW_PRICE_THRESHOLD = 10_000
FLIP_WINDOW_DAYS = 365
FLIP_RATIO = 2.0

DISTRESS_DEED_KINDS = ("sheriff", "condemnation")
NON_MARKET_DEED_KINDS = ("land_bank", "deceased", "adverse_possession", "other")

# Tokens that mark a legal-entity party rather than a person. Uppercase match;
# grantor/grantee strings in rtt_summary are uppercase free text.
ENTITY_TOKENS = [
    "LLC",
    "LLP",
    "INC",
    "CORP",
    "CORPORATION",
    "COMPANY",
    "BANK",
    "TRUST",
    "PARTNERSHIP",
    "PARTNERS",
    "AUTHORITY",
    "REDEVELOPMENT",
    "HOUSING",
    "COMMONWEALTH",
    "HUD",
    "SECRETARY",
    "FANNIE",
    "FREDDIE",
    "PROPERTIES",
    "REALTY",
    "HOLDINGS",
    "DEVELOPMENT",
    "CONSTRUCTION",
    "INVESTMENTS",
    "GROUP",
    "EXECUTOR",
    "ADMINISTRATOR",
    "MORTGAGE",
    "FINANCE",
    "CREDIT",
]
_ENTITY_REGEX = r"\b(" + "|".join(ENTITY_TOKENS) + r")\b"


def _entity_flag(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.to_uppercase()
        .str.contains(_ENTITY_REGEX)
        .fill_null(False)
    )


def _name_tokens(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.to_uppercase()
        .str.extract_all(r"[A-Z]{3,}")
        .list.eval(pl.element().filter(~pl.element().is_in(ENTITY_TOKENS)))
    )


def _resale_flags(deeds: pl.LazyFrame) -> pl.LazyFrame:
    """Per-record flags computed over each parcel's chain of priced sales."""
    priced = (
        deeds.filter(
            pl.col("has_opa_link")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price").fill_null(0) > 1)
        )
        .sort("opa_account_num", "sale_date")
        .with_columns(
            pl.col("sale_price").shift(1).over("opa_account_num").alias("prev_price"),
            pl.col("sale_date").shift(1).over("opa_account_num").alias("prev_date"),
        )
        .with_columns(
            (pl.col("sale_date") - pl.col("prev_date")).dt.total_days().alias("days_since_prev")
        )
        .with_columns(
            (
                (pl.col("days_since_prev") < FLIP_WINDOW_DAYS)
                & (pl.col("sale_price") == pl.col("prev_price"))
            )
            .fill_null(False)
            .alias("dup_price_within_year"),
            (
                (pl.col("days_since_prev") < FLIP_WINDOW_DAYS)
                & (
                    (pl.col("sale_price") / pl.col("prev_price") >= FLIP_RATIO)
                    | (pl.col("sale_price") / pl.col("prev_price") <= 1 / FLIP_RATIO)
                )
            )
            .fill_null(False)
            .alias("rapid_price_swing"),
        )
        .select("record_id", "days_since_prev", "dup_price_within_year", "rapid_price_swing")
    )
    return deeds.join(priced, on="record_id", how="left").with_columns(
        pl.col("dup_price_within_year").fill_null(False),
        pl.col("rapid_price_swing").fill_null(False),
    )


def classify_sales(deeds: pl.LazyFrame, opa: pl.LazyFrame) -> pl.LazyFrame:
    """Classify every staged deed row. Pure LazyFrame function; see module docstring."""
    property_info = opa.select(
        pl.col("parcel_number").alias("opa_account_num"),
        "category_code_description",
        "total_livable_area",
    )
    lf = deeds.join(property_info, on="opa_account_num", how="left")
    lf = _resale_flags(lf)

    lf = lf.with_columns(
        pl.col("zip_code").cast(pl.String).str.slice(0, 5).alias("zip5"),
        pl.col("sale_date").dt.year().alias("sale_year"),
        _entity_flag("grantors").alias("non_person_seller"),
        _entity_flag("grantees").alias("non_person_buyer"),
        (_name_tokens("grantors").list.set_intersection(_name_tokens("grantees")).list.len() > 0)
        .fill_null(False)
        .alias("possible_related"),
        pl.col("deed_kind").is_in(DISTRESS_DEED_KINDS).alias("is_distress_deed"),
        pl.col("deed_kind").is_in(NON_MARKET_DEED_KINDS).alias("is_non_market_deed"),
        (~pl.col("is_nominal") & (pl.col("sale_price").fill_null(0) <= LOW_PRICE_THRESHOLD)).alias(
            "is_low_price"
        ),
    )

    # Group price statistics from the eligible pool only, so nominal/distressed
    # sales don't contaminate the reference distribution.
    eligible = (
        pl.col("has_opa_link")
        & ~pl.col("is_multi_parcel")
        & pl.col("sale_date").is_not_null()
        & pl.col("deed_kind").is_in(["standard", "miscellaneous"])
        & (pl.col("sale_price").fill_null(0) > LOW_PRICE_THRESHOLD)
        & ~pl.col("dup_price_within_year")
    )
    log_price = pl.col("sale_price").log()
    ppsf = pl.when(pl.col("total_livable_area").fill_null(0) > 0).then(
        pl.col("sale_price") / pl.col("total_livable_area")
    )
    lf = lf.with_columns(
        eligible.alias("in_reference_pool"),
        ppsf.alias("price_per_sqft"),
        pl.when(
            pl.col("opa_account_num").cast(pl.String).str.starts_with(config.CONDO_ACCOUNT_PREFIX)
        )
        .then(pl.lit("CONDO UNIT"))
        .otherwise(pl.col("category_code_description"))
        .alias("pool_category"),
    )

    group_keys = ["zip5", "pool_category", "sale_year"]
    stats = (
        lf.filter(pl.col("in_reference_pool"))
        .group_by(group_keys)
        .agg(
            pl.len().alias("group_n"),
            log_price.mean().alias("group_log_price_mean"),
            log_price.std().alias("group_log_price_std"),
            pl.col("price_per_sqft").log().mean().alias("group_log_ppsf_mean"),
            pl.col("price_per_sqft").log().std().alias("group_log_ppsf_std"),
        )
    )
    lf = lf.join(stats, on=group_keys, how="left").with_columns(
        pl.when((pl.col("group_n") >= MIN_GROUP_SIZE) & (pl.col("group_log_price_std") > 0))
        .then((log_price - pl.col("group_log_price_mean")) / pl.col("group_log_price_std"))
        .alias("z_log_price"),
        pl.when((pl.col("group_n") >= MIN_GROUP_SIZE) & (pl.col("group_log_ppsf_std") > 0))
        .then(
            (pl.col("price_per_sqft").log() - pl.col("group_log_ppsf_mean"))
            / pl.col("group_log_ppsf_std")
        )
        .alias("z_log_ppsf"),
    )

    # Outlier detection on price-PER-SQFT only (size-normalized). Total log-price
    # scales with home size, so a large house in a small-home pool tripped the
    # old `z_log_price` term even at an ordinary $/sqft, excluding legitimate
    # high-value sales (e.g. 106 Rochelle Ave: $927.5k in 2022, ppsf normal,
    # matching OPA's value within 0.3%). A genuine price error still shows up as a
    # ppsf outlier, so nothing real is lost; z_log_price stays for diagnostics.
    is_price_outlier = (
        pl.col("in_reference_pool") & (pl.col("z_log_ppsf").abs() >= Z_THRESHOLD)
    ).fill_null(False)
    lf = lf.with_columns(is_price_outlier.alias("is_price_outlier"))

    reason = [
        ("multi_parcel", pl.col("is_multi_parcel")),
        ("no_opa_link", ~pl.col("has_opa_link")),
        ("no_sale_date", pl.col("sale_date").is_null()),
        ("dup_price_within_year", pl.col("dup_price_within_year")),
        ("distress_deed", pl.col("is_distress_deed")),
        ("non_market_deed", pl.col("is_non_market_deed")),
        ("nominal_consideration", pl.col("is_nominal")),
        ("low_price", pl.col("is_low_price")),
        ("price_outlier_high", pl.col("is_price_outlier") & (pl.col("z_log_ppsf") > 0)),
        ("price_outlier_low", pl.col("is_price_outlier") & (pl.col("z_log_ppsf") <= 0)),
        ("rapid_price_swing", pl.col("rapid_price_swing")),
        ("non_person_seller", pl.col("non_person_seller")),
        ("non_person_buyer", pl.col("non_person_buyer")),
        ("possible_related_parties", pl.col("possible_related")),
    ]
    reasons = pl.concat_list(
        [
            pl.when(condition.fill_null(False))
            .then(pl.lit(code))
            .otherwise(pl.lit(None, dtype=pl.String))
            for code, condition in reason
        ]
    ).list.drop_nulls()

    is_excluded = (
        pl.col("is_multi_parcel")
        | ~pl.col("has_opa_link")
        | pl.col("sale_date").is_null()
        | pl.col("dup_price_within_year")
    )
    is_suspect = pl.col("is_low_price") | pl.col("is_price_outlier") | pl.col("rapid_price_swing")
    status = (
        pl.when(is_excluded)
        .then(pl.lit(ValidityStatus.EXCLUDED))
        .when(pl.col("is_distress_deed") | pl.col("is_non_market_deed"))
        .then(pl.lit(ValidityStatus.NOT_ARMS_LENGTH))
        .when(pl.col("is_nominal"))
        .then(pl.lit(ValidityStatus.NOMINAL))
        .when(is_suspect)
        .then(pl.lit(ValidityStatus.SUSPECT))
        .otherwise(pl.lit(ValidityStatus.ARMS_LENGTH))
    )
    any_supplementary = (
        pl.col("non_person_seller") | pl.col("non_person_buyer") | pl.col("possible_related")
    )
    confidence = (
        pl.when(status == ValidityStatus.ARMS_LENGTH)
        .then(pl.when(any_supplementary).then(0.75).otherwise(0.9))
        .when(status == ValidityStatus.SUSPECT)
        .then(0.5)
        .otherwise(0.95)
    )

    return lf.with_columns(
        status.alias("validity_status"),
        reasons.alias("validity_reasons"),
        confidence.alias("confidence"),
    ).select(
        pl.col("record_id").alias("sale_id"),
        pl.col("opa_account_num").alias("parcel_id"),
        "sale_date",
        "sale_price",
        "deed_kind",
        "validity_status",
        "validity_reasons",
        "confidence",
        "zip5",
        "category_code_description",
        "pool_category",
        "sale_year",
        "price_per_sqft",
        "z_log_price",
        "z_log_ppsf",
        "group_n",
        "days_since_prev",
        "non_person_seller",
        "non_person_buyer",
        "possible_related",
        "in_reference_pool",
    )


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_sale_validity(data_dir: Path | None = None) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    deeds_path = root / "staged" / "deeds.parquet"
    opa_path = root / "staged" / "opa_properties.parquet"
    for path in (deeds_path, opa_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `fair-measure stage` first")

    frame = classify_sales(pl.scan_parquet(deeds_path), pl.scan_parquet(opa_path)).collect()

    marts_dir = root / "marts"
    marts_dir.mkdir(parents=True, exist_ok=True)
    path = marts_dir / "sale_validity.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    frame.write_parquet(tmp, compression="zstd")
    tmp.rename(path)

    inputs = []
    for staged_path in (deeds_path, opa_path):
        staged_manifest = read_derived_manifest(staged_path)
        inputs.append(
            InputRef(
                dataset=f"staged/{staged_manifest.table}",
                fetched_at=staged_manifest.built_at.isoformat(),
            )
        )
    manifest = DerivedManifest(
        layer="marts",
        table="sale_validity",
        built_at=datetime.now(UTC),
        row_count=frame.height,
        inputs=inputs,
        package_version=__version__,
    )
    write_derived_manifest(manifest, path)
    logger.info("sale_validity: %s rows -> %s", f"{frame.height:,}", path)
    return BuildResult(path=path, manifest=manifest)
