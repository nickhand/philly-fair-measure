"""Point-in-time renovation/flip episode features.

A renovation episode is a dated sequence: acquisition, permit activity, and
an observation date (a resale date in training or the valuation date when
scoring).  Permit events are included only when they fall strictly inside the
sequence, which prevents later work from leaking into an earlier estimate.

Historical resale recovery and its weak label are evaluation/training-only.
They are deliberately absent from current-property features.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import numpy as np
import polars as pl

from philly_fair_measure.features.sale_features import (
    is_reno_permit,
    permit_completion_date,
)

EPISODE_MIN_DAYS: Final = 120
EPISODE_MAX_DAYS: Final = 1_095
HIGH_RECOVERY_LOG: Final = float(np.log(1.60))

EPISODE_RAW_FEATURES: Final = (
    "episode_eligible",
    "episode_days_since_acquisition",
    "episode_permits_since_acquisition",
    "episode_reno_permits_since_acquisition",
    "episode_other_permits_since_acquisition",
    "episode_completed_permits_since_acquisition",
    "episode_completed_reno_since_acquisition",
    "episode_active_permits_since_acquisition",
    "episode_active_reno_since_acquisition",
    "episode_days_to_first_permit",
    "episode_days_since_last_permit",
    "episode_permit_span_days",
    "episode_completion_share",
    "episode_permit_bundle",
    "episode_trade_stack",
    "episode_prior_discount_log",
)

_COUNT_FEATURES: Final = (
    "episode_permits_since_acquisition",
    "episode_reno_permits_since_acquisition",
    "episode_other_permits_since_acquisition",
    "episode_completed_permits_since_acquisition",
    "episode_completed_reno_since_acquisition",
    "episode_active_permits_since_acquisition",
    "episode_active_reno_since_acquisition",
)


def _number(frame: pl.DataFrame, name: str) -> pl.Expr:
    if name in frame.columns:
        return pl.col(name).cast(pl.Float64, strict=False)
    return pl.lit(None, dtype=pl.Float64)


def _permit_events(permits: pl.DataFrame) -> pl.DataFrame:
    columns = set(permits.columns)
    return permits.filter(
        pl.col("opa_account_num").is_not_null() & pl.col("permitissuedate_parsed").is_not_null()
    ).select(
        pl.col("opa_account_num").alias("parcel_id"),
        pl.col("permitissuedate_parsed").alias("episode_permit_date"),
        permit_completion_date(columns).alias("episode_completion_date"),
        (is_reno_permit() if "typeofwork" in columns else pl.lit(False)).alias("episode_is_reno"),
    )


def _episode_activity(
    ordered: pl.DataFrame,
    events: pl.DataFrame,
    *,
    observation_col: str,
    previous_sale_col: str,
) -> pl.DataFrame:
    eligible = ordered.filter(pl.col("episode_eligible") > 0).select(
        "__episode_row_id", "parcel_id", observation_col, previous_sale_col
    )
    return (
        eligible.join(events, on="parcel_id", how="inner")
        .filter(
            (pl.col("episode_permit_date") > pl.col(previous_sale_col))
            & (pl.col("episode_permit_date") < pl.col(observation_col))
        )
        .with_columns(
            (
                pl.col("episode_completion_date").is_not_null()
                & (pl.col("episode_completion_date") <= pl.col(observation_col))
            ).alias("episode_completed_by_observation"),
            (pl.col("episode_permit_date") - pl.col(previous_sale_col))
            .dt.total_days()
            .alias("episode_days_after_acquisition"),
            (pl.col(observation_col) - pl.col("episode_permit_date"))
            .dt.total_days()
            .alias("episode_days_before_observation"),
        )
        .group_by("__episode_row_id")
        .agg(
            pl.len().alias("episode_permits_since_acquisition"),
            pl.col("episode_is_reno").sum().alias("episode_reno_permits_since_acquisition"),
            (~pl.col("episode_is_reno")).sum().alias("episode_other_permits_since_acquisition"),
            pl.col("episode_completed_by_observation")
            .sum()
            .alias("episode_completed_permits_since_acquisition"),
            (pl.col("episode_is_reno") & pl.col("episode_completed_by_observation"))
            .sum()
            .alias("episode_completed_reno_since_acquisition"),
            (~pl.col("episode_completed_by_observation"))
            .sum()
            .alias("episode_active_permits_since_acquisition"),
            (pl.col("episode_is_reno") & ~pl.col("episode_completed_by_observation"))
            .sum()
            .alias("episode_active_reno_since_acquisition"),
            pl.col("episode_days_after_acquisition").min().alias("episode_days_to_first_permit"),
            pl.col("episode_days_before_observation").min().alias("episode_days_since_last_permit"),
            (pl.col("episode_permit_date").max() - pl.col("episode_permit_date").min())
            .dt.total_days()
            .alias("episode_permit_span_days"),
        )
    )


def _finish_raw_features(ordered: pl.DataFrame, activity: pl.DataFrame) -> pl.DataFrame:
    out = ordered.join(activity, on="__episode_row_id", how="left").with_columns(
        *[pl.col(name).cast(pl.Float64).fill_null(0.0) for name in _COUNT_FEATURES]
    )
    permit_count = pl.col("episode_permits_since_acquisition").cast(pl.Float64)
    completed_count = pl.col("episode_completed_permits_since_acquisition").cast(pl.Float64)
    prior_discount = _number(out, "mkt_knn_price_anchor_log") - _number(
        out, "mkt_parcel_prev_log_price_ref"
    )
    return out.with_columns(
        pl.when(permit_count > 0)
        .then(completed_count / permit_count)
        .otherwise(0.0)
        .alias("episode_completion_share"),
        (permit_count >= 3).cast(pl.Float64).alias("episode_permit_bundle"),
        (
            (pl.col("episode_other_permits_since_acquisition") >= 3)
            & (pl.col("episode_reno_permits_since_acquisition") == 0)
        )
        .cast(pl.Float64)
        .alias("episode_trade_stack"),
        prior_discount.alias("episode_prior_discount_log"),
    )


def add_renovation_episode_features(frame: pl.DataFrame, permits: pl.DataFrame) -> pl.DataFrame:
    """Attach exact acquisition-to-resale features and weak recovery labels.

    The input order is preserved.  The recovery and label columns must never
    be included in a valuation predictor; they exist to train and audit the
    auxiliary transition classifier.
    """
    ordered = (
        frame.with_row_index("__episode_original_order")
        .sort("parcel_id", "sale_date", "sale_id")
        .with_row_index("__episode_row_id")
        .with_columns(
            pl.col("sale_date").shift(1).over("parcel_id").alias("episode_prev_sale_date"),
            pl.col("sale_price").shift(1).over("parcel_id").alias("episode_prev_sale_price"),
            pl.col("time_adj_log").shift(1).over("parcel_id").alias("episode_prev_time_adj_log"),
        )
    )
    ordered = ordered.with_columns(
        (pl.col("sale_date") - pl.col("episode_prev_sale_date"))
        .dt.total_days()
        .alias("episode_days_since_acquisition")
    ).with_columns(
        pl.col("episode_days_since_acquisition")
        .is_between(EPISODE_MIN_DAYS, EPISODE_MAX_DAYS)
        .fill_null(False)
        .cast(pl.Float64)
        .alias("episode_eligible")
    )
    activity = _episode_activity(
        ordered,
        _permit_events(permits),
        observation_col="sale_date",
        previous_sale_col="episode_prev_sale_date",
    )
    out = _finish_raw_features(ordered, activity)
    recovery = (
        pl.col("sale_price").log()
        + pl.col("time_adj_log").cast(pl.Float64).fill_null(0.0)
        - pl.col("episode_prev_sale_price").log()
        - pl.col("episode_prev_time_adj_log").cast(pl.Float64).fill_null(0.0)
    )
    out = out.with_columns(
        pl.when(pl.col("episode_eligible") > 0)
        .then(recovery)
        .otherwise(None)
        .alias("episode_recovery_log")
    )
    permit_confirmed = (pl.col("episode_permit_bundle") > 0) | (
        pl.col("episode_reno_permits_since_acquisition") > 0
    )
    return (
        out.with_columns(
            pl.when(pl.col("episode_eligible") > 0)
            .then((pl.col("episode_recovery_log") >= HIGH_RECOVERY_LOG).cast(pl.Int8))
            .otherwise(None)
            .alias("episode_high_recovery_label"),
            pl.when(pl.col("episode_eligible") > 0)
            .then(
                ((pl.col("episode_recovery_log") >= HIGH_RECOVERY_LOG) & permit_confirmed).cast(
                    pl.Int8
                )
            )
            .otherwise(None)
            .alias("episode_permit_confirmed_label"),
        )
        .sort("__episode_original_order")
        .drop("__episode_row_id", "__episode_original_order")
    )


def add_current_renovation_episode_features(
    frame: pl.DataFrame,
    permits: pl.DataFrame,
    valuation_date: datetime,
    *,
    previous_sale_col: str = "last_sale_date",
) -> pl.DataFrame:
    """Attach acquisition-to-valuation-date features without outcome labels."""
    ordered = (
        frame.with_row_index("__episode_original_order")
        .with_row_index("__episode_row_id")
        .with_columns(pl.lit(valuation_date).alias("__episode_observation_date"))
        .with_columns(
            (pl.col("__episode_observation_date") - pl.col(previous_sale_col))
            .dt.total_days()
            .alias("episode_days_since_acquisition")
        )
        .with_columns(
            pl.col("episode_days_since_acquisition")
            .is_between(EPISODE_MIN_DAYS, EPISODE_MAX_DAYS)
            .fill_null(False)
            .cast(pl.Float64)
            .alias("episode_eligible")
        )
    )
    activity = _episode_activity(
        ordered,
        _permit_events(permits),
        observation_col="__episode_observation_date",
        previous_sale_col=previous_sale_col,
    )
    return (
        _finish_raw_features(ordered, activity)
        .sort("__episode_original_order")
        .drop("__episode_row_id", "__episode_original_order", "__episode_observation_date")
    )
