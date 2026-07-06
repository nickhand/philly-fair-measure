"""Feature table for EVERY residential property at a valuation date.

The sale-features mart answers "what did sold properties look like at their
sale dates"; this module answers "what does every property look like *today*"
(or any chosen valuation date) so trained models can price the full roll.

Semantics mirror features/sale_features.py exactly, with the target sale
replaced by a common valuation date:

- block rolling averages (price and $/sqft): time-weighted means of
  arms-length sales on the property's block in the 5 years up to the
  valuation date, excluding the property's own sales (leave-own-parcel-out by
  aggregate subtraction — every parcel shares one date).
- kNN $/sqft surface: nearest prior sales in the trailing window
  (features/spatial.py), own parcel excluded.
- market area / district / time adjustment: from the learned market-area and
  price-index marts; at the valuation date the adjustment is ~0 by
  construction (index normalized to the latest month).
- parcel prior-sale, permit/violation event windows, style/era: as in
  sale_features.

Characteristics remain current_only — for scoring "today" that is exactly
right, since today's roll is the best available description of today's stock.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from philly_fair_measure.features.market_areas import project_xy
from philly_fair_measure.features.price_index import with_time_adjustment
from philly_fair_measure.features.sale_features import (
    _CHAR_RENAMES,
    _LOC_RENAMES,
    DISTRESS_TENURE_COUNTS,
    PPSF_AREA_BOUNDS,
    ROLL_WINDOW_DAYS,
    SEVERE_PRIORITIES,
    _block_id,
    _recency_weight,
    distress_tenure_features,
    era_expr,
    financing_features,
    is_reno_permit,
    join_delinquencies,
    join_parcel_shapes,
    join_proximity,
    style_expr,
)
from philly_fair_measure.features.spatial import (
    NEW_BUILD_LAG_YEARS,
    NEWBUILD_KNN_K,
    knn_ppsf_at_date,
)
from philly_fair_measure.models.baseline import RESIDENTIAL_CATEGORIES


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
    market_areas: pl.LazyFrame | None = None,
    price_index: pl.DataFrame | None = None,
    parcels: pl.LazyFrame | None = None,
    demolitions: pl.LazyFrame | None = None,
    delinquencies: pl.LazyFrame | None = None,
    proximity: pl.LazyFrame | None = None,
    complaints: pl.LazyFrame | None = None,
    investigations: pl.LazyFrame | None = None,
    rental_licenses: pl.LazyFrame | None = None,
    appeals: pl.LazyFrame | None = None,
    mortgages: pl.LazyFrame | None = None,
) -> pl.DataFrame:
    from philly_fair_measure.config import CONDO_ACCOUNT_PREFIX

    base = (
        opa.filter(
            pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES)
            # condos (88-prefix) are out of residential scope; they need a
            # dedicated model (docs/ccao-lessons.md condo playbook)
            & ~pl.col("parcel_number").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
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
    if market_areas is not None:
        areas = market_areas.select(
            "parcel_id", "market_area", "district", "ma_med_adj_log_ppsf"
        ).collect()
    else:
        areas = pl.DataFrame(
            schema={
                "parcel_id": pl.String,
                "market_area": pl.String,
                "district": pl.String,
                "ma_med_adj_log_ppsf": pl.Float64,
            }
        )
    base = base.join(areas, on="parcel_id", how="left").rename(
        {"market_area": "loc_market_area", "district": "loc_district"}
    )

    pool = _arms_length_sales(sales, valuation_date)
    # sale-side context: block, own area (for $/sqft), coordinates, district
    sale_context = base.select(
        "parcel_id",
        "loc_block_id",
        "loc_district",
        pl.col("total_livable_area").alias("livable_area"),
        pl.col("year_built_parsed").alias("year_built"),
        "lon",
        "lat",
        "lonlat_status",
    ).unique(subset=["parcel_id"])
    pool = pool.join(sale_context, on="parcel_id", how="left")
    if price_index is not None:
        pool = with_time_adjustment(pool, price_index)
        base_adj = with_time_adjustment(
            base.with_columns(pl.lit(valuation_date).alias("_val_date")),
            price_index,
            date_col="_val_date",
        ).drop("_val_date")
    else:
        pool = pool.with_columns(pl.lit(0.0).alias("time_adj_log"))
        base_adj = base.with_columns(pl.lit(0.0).alias("time_adj_log"))
    base = base_adj

    lo_a, hi_a = PPSF_AREA_BOUNDS
    windowed = (
        pool.with_columns(
            (pl.lit(valuation_date) - pl.col("sale_date")).dt.total_days().alias("days_ago")
        )
        .filter(
            (pl.col("days_ago") > 0)
            & (pl.col("days_ago") <= ROLL_WINDOW_DAYS)
            & pl.col("loc_block_id").is_not_null()
        )
        .with_columns(_recency_weight(pl.col("days_ago")).alias("w"))
        .with_columns(
            (pl.col("w") * pl.col("sale_price")).alias("wp"),
            pl.when(pl.col("livable_area").is_between(lo_a, hi_a))
            .then(pl.col("w") * (pl.col("sale_price") / pl.col("livable_area")))
            .otherwise(None)
            .alias("wppsf"),
            pl.when(pl.col("livable_area").is_between(lo_a, hi_a))
            .then(pl.col("w"))
            .otherwise(0.0)
            .alias("w_ppsf"),
        )
    )
    block_totals = windowed.group_by("loc_block_id").agg(
        pl.col("w").sum().alias("block_w"),
        pl.col("wp").sum().alias("block_wp"),
        pl.col("wppsf").sum().alias("block_wppsf"),
        pl.col("w_ppsf").sum().alias("block_w_ppsf"),
        pl.len().alias("block_n"),
    )
    own_totals = windowed.group_by("loc_block_id", "parcel_id").agg(
        pl.col("w").sum().alias("own_w"),
        pl.col("wp").sum().alias("own_wp"),
        pl.col("wppsf").sum().alias("own_wppsf"),
        pl.col("w_ppsf").sum().alias("own_w_ppsf"),
        pl.len().alias("own_n"),
    )

    prior_sales = (
        pool.sort("parcel_id", "sale_date")
        .group_by("parcel_id")
        .agg(
            pl.len().alias("mkt_parcel_n_prior_sales"),
            pl.col("sale_date").last().alias("last_sale_date"),
            pl.col("sale_price").last().alias("mkt_parcel_prev_price"),
            (pl.col("sale_price").log() + pl.col("time_adj_log"))
            .last()
            .alias("mkt_parcel_prev_log_price_ref"),
        )
        .with_columns(
            (pl.lit(valuation_date) - pl.col("last_sale_date"))
            .dt.total_days()
            .alias("mkt_parcel_days_since_prev")
        )
        .drop("last_sale_date")
    )

    # kNN surfaces from the trailing window (own parcel excluded inside):
    # the general surface plus the new-construction surface, whose evidence
    # is restricted to sales of then-new homes (features/spatial.py)
    knn_points = (
        pool.filter(
            (pl.col("lonlat_status") == "ok") & pl.col("livable_area").is_between(lo_a, hi_a)
        )
        .with_columns((pl.col("sale_price") / pl.col("livable_area")).alias("ppsf"))
        .filter(pl.col("ppsf").is_between(10.0, 2000.0))
        .with_columns(
            (pl.col("ppsf").log() + pl.col("time_adj_log")).alias("adj_log_ppsf"),
            *project_xy(pl.col("lon"), pl.col("lat")),
            (
                pl.col("year_built").fill_null(0)
                >= pl.col("sale_date").dt.year() - NEW_BUILD_LAG_YEARS
            ).alias("_new_at_sale"),
        )
        .select("parcel_id", "x_m", "y_m", "sale_date", "adj_log_ppsf", "_new_at_sale")
    )
    knn_targets = (
        base.filter(pl.col("lonlat_status") == "ok")
        .select("parcel_id", "lon", "lat")
        .with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
        .select("parcel_id", "x_m", "y_m")
    )
    knn = knn_ppsf_at_date(knn_points, knn_targets, valuation_date).join(
        knn_ppsf_at_date(
            knn_points,
            knn_targets,
            valuation_date,
            k=NEWBUILD_KNN_K,
            prefix="mkt_newbuild_knn",
            tree_col="_new_at_sale",
        ),
        on="parcel_id",
        how="left",
    )

    # minimal fixtures may omit typeofwork; treat as non-renovation
    has_typeofwork = "typeofwork" in permits.collect_schema().names()
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
            (is_reno_permit() if has_typeofwork else pl.lit(False)).alias("is_reno"),
        )
        .collect()
        .group_by("parcel_id")
        .agg(
            (pl.col("days_before") <= ROLL_WINDOW_DAYS).sum().alias("evt_n_permits_5y_before"),
            pl.col("days_before").min().alias("evt_days_since_last_permit"),
            ((pl.col("days_before") <= ROLL_WINDOW_DAYS) & pl.col("is_reno"))
            .sum()
            .alias("evt_n_reno_permits_5y_before"),
            pl.col("days_before")
            .filter(pl.col("is_reno"))
            .min()
            .alias("evt_days_since_last_reno_permit"),
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
            pl.col("caseprioritydesc")
            .cast(pl.String)
            .is_in(SEVERE_PRIORITIES)
            .fill_null(False)
            .alias("is_severe"),
        )
        .collect()
        .with_columns(
            ((pl.col("days_before") > 0) & (pl.col("days_before") <= ROLL_WINDOW_DAYS)).alias(
                "in_window"
            ),
            (pl.col("resolved_date").is_null() | (pl.col("resolved_date") > valuation_date)).alias(
                "is_open"
            ),
        )
        .group_by("parcel_id")
        .agg(
            pl.col("in_window").sum().alias("evt_n_violations_5y_before"),
            pl.col("is_open").sum().alias("evt_n_open_violations_at_sale"),
            (pl.col("in_window") & pl.col("is_severe"))
            .sum()
            .alias("evt_n_severe_violations_5y_before"),
            (pl.col("is_open") & pl.col("is_severe")).sum().alias("evt_n_open_severe_at_sale"),
        )
    )
    if demolitions is not None:
        demo_feats = (
            demolitions.filter(
                pl.col("opa_account_num").is_not_null()
                & pl.coalesce("completed_date_parsed", "start_date_parsed").is_not_null()
                & (pl.coalesce("completed_date_parsed", "start_date_parsed") < valuation_date)
            )
            .select(
                pl.col("opa_account_num").alias("parcel_id"),
                (pl.lit(valuation_date) - pl.coalesce("completed_date_parsed", "start_date_parsed"))
                .dt.total_days()
                .alias("days_before"),
            )
            .collect()
            .group_by("parcel_id")
            .agg(
                pl.len().alias("evt_n_demolitions_before"),
                pl.col("days_before").min().alias("evt_demo_days_since"),
            )
        )
    else:
        demo_feats = pl.DataFrame(
            schema={
                "parcel_id": pl.String,
                "evt_n_demolitions_before": pl.UInt32,
                "evt_demo_days_since": pl.Int64,
            }
        )

    epoch_days = (valuation_date - datetime(1997, 1, 1)).days
    features = (
        base.join(block_totals, on="loc_block_id", how="left")
        .join(own_totals, on=["loc_block_id", "parcel_id"], how="left")
        .with_columns(
            *[
                pl.col(c).fill_null(0.0)
                for c in (
                    "own_w",
                    "own_wp",
                    "own_wppsf",
                    "own_w_ppsf",
                    "block_w",
                    "block_wp",
                    "block_wppsf",
                    "block_w_ppsf",
                )
            ],
            pl.col("own_n").fill_null(0),
            pl.col("block_n").fill_null(0),
        )
        .with_columns(
            pl.when(pl.col("block_w") - pl.col("own_w") > 0)
            .then((pl.col("block_wp") - pl.col("own_wp")) / (pl.col("block_w") - pl.col("own_w")))
            .alias("mkt_block_roll_mean_price"),
            pl.when(pl.col("block_w_ppsf") - pl.col("own_w_ppsf") > 0)
            .then(
                (pl.col("block_wppsf") - pl.col("own_wppsf"))
                / (pl.col("block_w_ppsf") - pl.col("own_w_ppsf"))
            )
            .alias("mkt_block_roll_ppsf"),
            (pl.col("block_n") - pl.col("own_n")).alias("mkt_block_roll_n"),
        )
        .drop(
            "block_w",
            "block_wp",
            "block_wppsf",
            "block_w_ppsf",
            "block_n",
            "own_w",
            "own_wp",
            "own_wppsf",
            "own_w_ppsf",
            "own_n",
        )
        .join(prior_sales, on="parcel_id", how="left")
        .join(knn, on="parcel_id", how="left")
        .join(permit_events, on="parcel_id", how="left")
        .join(violation_events, on="parcel_id", how="left")
        .join(demo_feats, on="parcel_id", how="left")
        .join(
            distress_tenure_features(
                base.select(
                    pl.col("parcel_id").alias("sale_id"),
                    "parcel_id",
                    pl.lit(valuation_date).alias("sale_date"),
                ),
                complaints,
                investigations,
                rental_licenses,
                appeals,
            ).rename({"sale_id": "parcel_id"}),
            on="parcel_id",
            how="left",
        )
        .join(
            financing_features(
                base.select(
                    pl.col("parcel_id").alias("sale_id"),
                    "parcel_id",
                    pl.lit(valuation_date).alias("sale_date"),
                ),
                mortgages,
                pool.select("parcel_id", "sale_date"),
            ).rename({"sale_id": "parcel_id"}),
            on="parcel_id",
            how="left",
        )
        .rename({**_CHAR_RENAMES, **_LOC_RENAMES})
        .rename(
            {
                "category_code_description": "char_category",
                "ma_med_adj_log_ppsf": "mkt_area_level_log_ppsf",
            }
        )
        .with_columns(
            style_expr(),
            era_expr(),
            pl.col("mkt_block_roll_n").fill_null(0),
            pl.col("mkt_knn_n").fill_null(0),
            pl.col("mkt_newbuild_knn_n").fill_null(0),
            pl.col("mkt_parcel_n_prior_sales").fill_null(0),
            (pl.col("char_year_built").fill_null(0) >= valuation_date.year - NEW_BUILD_LAG_YEARS)
            .cast(pl.Float64)
            .alias("char_new_build"),
            pl.col("evt_n_permits_5y_before").fill_null(0),
            pl.col("evt_n_reno_permits_5y_before").fill_null(0),
            pl.col("evt_n_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_violations_at_sale").fill_null(0),
            pl.col("evt_n_severe_violations_5y_before").fill_null(0),
            pl.col("evt_n_open_severe_at_sale").fill_null(0),
            pl.col("evt_n_demolitions_before").fill_null(0),
            *[pl.col(c).fill_null(0.0) for c in DISTRESS_TENURE_COUNTS],
            pl.col("fin_n_mortgages_5y_before").fill_null(0.0),
            pl.col("fin_refi_5y_before").fill_null(0.0),
            pl.col("fin_hard_money_5y_before").fill_null(0.0),
            pl.lit(float(epoch_days)).alias("time_sale_epoch_days"),
            pl.lit((valuation_date.month - 1) // 3 + 1).alias("time_quarter"),
            pl.lit(valuation_date.month).alias("time_month"),
            pl.lit(valuation_date.isoweekday()).alias("time_weekday"),
        )
        .with_columns(
            # new-construction premium (see features/sale_features.py)
            (
                pl.col("char_new_build")
                * (pl.col("mkt_newbuild_knn_log_ppsf") - pl.col("mkt_knn_log_ppsf")).fill_null(0.0)
            ).alias("mkt_newbuild_premium"),
        )
        .drop("house_number_parsed", strict=False)
    )
    features = join_parcel_shapes(features, parcels)
    features = join_delinquencies(features, delinquencies)
    return join_proximity(features, proximity)
