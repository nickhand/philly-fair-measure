"""Parse raw temporal strings into typed columns with per-value status.

Raw snapshots keep temporal values as verbatim strings (see sources/carto.py).
Staging adds ``<col>_parsed`` and ``<col>_status`` next to the untouched raw
column. Status values:

    ok           parsed and within plausibility bounds
    missing      raw value is null
    invalid      raw value failed to parse
    implausible  parsed, but outside plausibility bounds (e.g. the year-206
                 sale date observed in opa_properties_public, or year_built "0")

``<col>_parsed`` is null unless status is ok, so downstream code can use parsed
columns directly; the raw column always retains the original value.
"""

from __future__ import annotations

import polars as pl

from philly_fair_measure.vocab import TemporalStatus

CARTO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MIN_PLAUSIBLE_YEAR = 1650
MAX_PLAUSIBLE_YEAR = 2035


def with_parsed_timestamp(
    lf: pl.LazyFrame,
    column: str,
    *,
    min_year: int = MIN_PLAUSIBLE_YEAR,
    max_year: int = MAX_PLAUSIBLE_YEAR,
) -> pl.LazyFrame:
    parsed = (
        pl.col(column)
        .cast(pl.String)  # tolerate all-null columns that infer as Null dtype
        .str.to_datetime(CARTO_TIMESTAMP_FORMAT, time_unit="us", strict=False)
    )
    plausible = parsed.dt.year().is_between(min_year, max_year)
    status = (
        pl.when(pl.col(column).is_null())
        .then(pl.lit(TemporalStatus.MISSING))
        .when(parsed.is_null())
        .then(pl.lit(TemporalStatus.INVALID))
        .when(~plausible)
        .then(pl.lit(TemporalStatus.IMPLAUSIBLE))
        .otherwise(pl.lit(TemporalStatus.OK))
    )
    return lf.with_columns(
        pl.when(plausible).then(parsed).otherwise(None).alias(f"{column}_parsed"),
        status.alias(f"{column}_status"),
    )


def with_parsed_year(
    lf: pl.LazyFrame,
    column: str,
    *,
    min_year: int = MIN_PLAUSIBLE_YEAR,
    max_year: int = MAX_PLAUSIBLE_YEAR,
) -> pl.LazyFrame:
    parsed = pl.col(column).cast(pl.String).str.strip_chars().cast(pl.Int32, strict=False)
    plausible = parsed.is_between(min_year, max_year)
    status = (
        pl.when(pl.col(column).is_null())
        .then(pl.lit(TemporalStatus.MISSING))
        .when(parsed.is_null())
        .then(pl.lit(TemporalStatus.INVALID))
        .when(~plausible)
        .then(pl.lit(TemporalStatus.IMPLAUSIBLE))
        .otherwise(pl.lit(TemporalStatus.OK))
    )
    return lf.with_columns(
        pl.when(plausible).then(parsed).otherwise(None).alias(f"{column}_parsed"),
        status.alias(f"{column}_status"),
    )
