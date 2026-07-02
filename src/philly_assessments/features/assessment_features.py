"""Feature table for EVERY residential property at a valuation date.

The sale-features mart answers "what did sold properties look like at their
sale dates"; this module answers "what does every property look like *today*"
(or any chosen valuation date) so trained models can price the full roll.

Semantics mirror features/sale_features.py exactly, with the target sale
replaced by a common valuation date:

- block rolling average: time-weighted mean of arms-length sales on the
  property's block in the 5 years up to the valuation date, excluding the
  property's own sales (leave-own-parcel-out, computed by aggregate
  subtraction rather than pair joins — every parcel shares one date).
- parcel prior-sale features: the property's own latest arms-length sale.
- event features: permits/violations strictly before the valuation date.
- time features: encodings of the valuation date (constant across rows).

Characteristics remain current_only — for scoring "today" that is exactly
right, since today's roll is the best available description of today's stock.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from philly_assessments.features.sale_features import (
    _CHAR_RENAMES,
    _LOC_RENAMES,
    ROLL_WINDOW_DAYS,
    _block_id,
    _recency_weight,
)
from philly_assessments.models.baseline import RESIDENTIAL_CATEGORIES


def _arms_length_sales(sales: pl.LazyFrame, valuation_date: datetime) -> pl.DataFrame:
    return (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") > 0)
            & (pl.col("sale_date") <= valuation_date)
        )
        .select("parcel_id", "sale_date", "sale_price")
        .collect()
    )


def assemble_assessment_features(
    opa: pl.LazyFrame,
    sales: pl.LazyFrame,
    permits: pl.LazyFrame,
    violations: pl.LazyFrame,
    valuation_date: datetime,
) -> pl.DataFrame:
    base = (
        opa.filter(pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES))
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("location").alias("address"),
            pl.col("market_value").alias("opa_market_value"),
            pl.col("zip_code").cast(pl.String).str.slice(0, 5).alias("loc_zip5"),
            pl.col("category_code_description"),
            "street_code",
            "house_number_parsed",
            *_CHAR_RENAMES,
            *[c for c in _LOC_RENAMES if c != "street_code"],
        )
        .collect()
        .with_columns(_block_id())
    )

    pool = _arms_length_sales(sales, valuation_date)
    windowed = (
        pool.with_columns(
            (pl.lit(valuation_date) - pl.col("sale_date")).dt.total_days().alias("days_ago")
        )
        .filter((pl.col("days_ago") > 0) & (pl.col("days_ago") <= ROLL_WINDOW_DAYS))
        .join(
            base.select("parcel_id", "loc_block_id").unique(subset=["parcel_id"]),
            on="parcel_id",
            how="left",
        )
        .filter(pl.col("loc_block_id").is_not_null())
        .with_columns(_recency_weight(pl.col("days_ago")).alias("w"))
        .with_columns((pl.col("w") * pl.col("sale_price")).alias("wp"))
    )
    block_totals = windowed.group_by("loc_block_id").agg(
        pl.col("w").sum().alias("block_w"),
        pl.col("wp").sum().alias("block_wp"),
        pl.len().alias("block_n"),
    )
    own_totals = windowed.group_by("loc_block_id", "parcel_id").agg(
        pl.col("w").sum().alias("own_w"),
        pl.col("wp").sum().alias("own_wp"),
        pl.len().alias("own_n"),
    )

    prior_sales = (
        pool.sort("parcel_id", "sale_date")
        .group_by("parcel_id")
        .agg(
            pl.len().alias("mkt_parcel_n_prior_sales"),
            pl.col("sale_date").last().alias("last_sale_date"),
            pl.col("sale_price").last().alias("mkt_parcel_prev_price"),
        )
        .with_columns(
            (pl.lit(valuation_date) - pl.col("last_sale_date"))
            .dt.total_days()
            .alias("mkt_parcel_days_since_prev")
        )
        .drop("last_sale_date")
    )

    permit_events = (
        permits.filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("permitissuedate_parsed").is_not_null()
            & (pl.col("permitissuedate_parsed") < valuation_date)
        )
        .select(
            pl.col("opa_account_num").alias("parcel_id"),
            (pl.lit(valuation_date) - pl.col("permitissuedate_parsed"))
            .dt.total_days()
            .alias("days_before"),
        )
        .collect()
        .group_by("parcel_id")
        .agg(
            (pl.col("days_before") <= ROLL_WINDOW_DAYS).sum().alias("evt_n_permits_5y_before"),
            pl.col("days_before").min().alias("evt_days_since_last_permit"),
        )
    )
    violation_events = (
        violations.filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("violationdate_parsed").is_not_null()
            & (pl.col("violationdate_parsed") <= valuation_date)
        )
        .select(
            pl.col("opa_account_num").alias("parcel_id"),
            (pl.lit(valuation_date) - pl.col("violationdate_parsed"))
            .dt.total_days()
            .alias("days_before"),
            pl.col("violationresolutiondate_parsed").alias("resolved_date"),
        )
        .collect()
        .group_by("parcel_id")
        .agg(
            ((pl.col("days_before") > 0) & (pl.col("days_before") <= ROLL_WINDOW_DAYS))
            .sum()
            .alias("evt_n_violations_5y_before"),
            (pl.col("resolved_date").is_null() | (pl.col("resolved_date") > valuation_date))
            .sum()
            .alias("evt_n_open_violations_at_sale"),
        )
    )

    epoch_days = (valuation_date - datetime(1997, 1, 1)).days
    features = (
        base.join(block_totals, on="loc_block_id", how="left")
        .join(own_totals, on=["loc_block_id", "parcel_id"], how="left")
        .with_columns(
            pl.col("own_w").fill_null(0.0),
            pl.col("own_wp").fill_null(0.0),
            pl.col("own_n").fill_null(0),
            pl.col("block_w").fill_null(0.0),
            pl.col("block_wp").fill_null(0.0),
            pl.col("block_n").fill_null(0),
        )
        .with_columns(
            pl.when(pl.col("block_w") - pl.col("own_w") > 0)
            .then(
                (pl.col("block_wp") - pl.col("own_wp")) / (pl.col("block_w") - pl.col("own_w"))
            )
            .alias("mkt_block_roll_mean_price"),
            (pl.col("block_n") - pl.col("own_n")).alias("mkt_block_roll_n"),
        )
        .drop("block_w", "block_wp", "block_n", "own_w", "own_wp", "own_n")
        .join(prior_sales, on="parcel_id", how="left")
        .join(permit_events, on="parcel_id", how="left")
        .join(violation_events, on="parcel_id", how="left")
        .rename({**_CHAR_RENAMES, **_LOC_RENAMES})
        .rename({"category_code_description": "char_category"})
        .with_columns(
            pl.col("mkt_block_roll_n").fill_null(0),
            pl.col("mkt_parcel_n_prior_sales").fill_null(0),
            pl.col("evt_n_permits_5y_before").fill_null(0),
            pl.col("evt_n_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_violations_at_sale").fill_null(0),
            pl.lit(float(epoch_days)).alias("time_sale_epoch_days"),
            pl.lit((valuation_date.month - 1) // 3 + 1).alias("time_quarter"),
            pl.lit(valuation_date.month).alias("time_month"),
            pl.lit(valuation_date.isoweekday()).alias("time_weekday"),
        )
        .drop("house_number_parsed", strict=False)
    )
    return features
