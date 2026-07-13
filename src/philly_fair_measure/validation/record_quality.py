"""Conservative, screen-only guards for ambiguous current property records.

These screen checks do not mechanically alter point features or estimates.
They identify cases where a numeric model-versus-OPA verdict is not defensible
because the public record does not describe a stable, internally coherent
home. The corresponding area-conflict feature separately enters the Bayesian
variance model.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

OPEN_CHANGE_OF_OCCUPANCY = "open_change_of_occupancy"
MULTIFAMILY_AREA_CONFLICT = "multifamily_area_conflict"

_ACTIVE_PERMIT_LOOKBACK_DAYS = 730
_MIN_FOOTPRINT_SQFT = 200.0
_MAX_LIVABLE_TO_GROSS_RATIO = 0.40


def _as_lazy(frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    return frame.lazy() if isinstance(frame, pl.DataFrame) else frame


def _open_change_permits(
    permits: pl.DataFrame | pl.LazyFrame, valuation_date: datetime
) -> pl.DataFrame:
    """Current issued change-of-occupancy permits, limited to a recent window.

    ``status=Issued`` comes from the latest permit snapshot and therefore says
    the work is authorized but not completed. The lookback avoids treating an
    ancient, administratively stale permit as evidence that today's property
    is still in transition.
    """
    lf = _as_lazy(permits)
    schema = lf.collect_schema().names()
    text_columns = [
        name
        for name in ("typeofwork", "permitdescription", "approvedscopeofwork")
        if name in schema
    ]
    if not {"opa_account_num", "permitissuedate_parsed", "status"}.issubset(schema):
        return pl.DataFrame(
            schema={"parcel_id": pl.String, "quality_open_change_permits": pl.UInt32}
        )
    scope = (
        pl.concat_str(
            [pl.col(name).cast(pl.String) for name in text_columns],
            separator=" ",
            ignore_nulls=True,
        )
        if text_columns
        else pl.lit("")
    )
    start = valuation_date - timedelta(days=_ACTIVE_PERMIT_LOOKBACK_DAYS)
    return (
        lf.filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("permitissuedate_parsed").is_between(start, valuation_date)
            & (pl.col("status").cast(pl.String).str.strip_chars().str.to_uppercase() == "ISSUED")
            & scope.str.to_uppercase().str.contains("CHANGE OF OCCUPANCY")
        )
        .group_by(pl.col("opa_account_num").cast(pl.String).alias("parcel_id"))
        .agg(pl.len().cast(pl.UInt32).alias("quality_open_change_permits"))
        .collect()
    )


def add_record_quality(
    features: pl.DataFrame,
    permits: pl.DataFrame | pl.LazyFrame,
    building_footprints: pl.DataFrame | pl.LazyFrame | None,
    valuation_date: datetime,
) -> pl.DataFrame:
    """Attach no-verdict reasons and their auditable supporting measurements.

    The multifamily check deliberately requires three independent pieces to
    agree before it fires: OPA says two-plus stories, the footprint height also
    supports two-plus floors, and the two story estimates differ by at most
    one. Only then do we call a sub-40% living-area ratio plus zero beds and
    baths an internal conflict. This is a precision-first guard, not an attempt
    to reconstruct living area from a footprint.
    """
    out = features.join(_open_change_permits(permits, valuation_date), on="parcel_id", how="left")
    out = out.with_columns(
        pl.col("quality_open_change_permits").fill_null(0),
        (pl.col("quality_open_change_permits").fill_null(0) > 0).alias(
            "quality_open_change_of_occupancy"
        ),
    )

    if building_footprints is None:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("bldg_footprint_sqft"),
            pl.lit(None, dtype=pl.Float64).alias("bldg_approx_height_ft"),
            pl.lit(None, dtype=pl.Float64).alias("quality_estimated_floors"),
            pl.lit(None, dtype=pl.Float64).alias("quality_livable_to_gross_ratio"),
            pl.lit(False).alias("quality_multifamily_area_conflict"),
        )
    else:
        footprint = _as_lazy(building_footprints).select(
            "parcel_id", "bldg_footprint_sqft", "bldg_approx_height_ft"
        )
        out = out.join(footprint.collect(), on="parcel_id", how="left")
        estimated_floors = (
            (pl.col("bldg_approx_height_ft").cast(pl.Float64) / 10.0).round(0).clip(1.0, 6.0)
        )
        out = out.with_columns(estimated_floors.alias("quality_estimated_floors"))
        gross = pl.col("bldg_footprint_sqft").cast(pl.Float64) * pl.col("char_stories").cast(
            pl.Float64
        )
        out = out.with_columns(
            pl.when(gross > 0)
            .then(pl.col("char_livable_area").cast(pl.Float64) / gross)
            .alias("quality_livable_to_gross_ratio")
        )
        supported_multistory = (
            (pl.col("char_stories").cast(pl.Float64).is_between(2.0, 6.0))
            & (pl.col("quality_estimated_floors") >= 2.0)
            & (
                (pl.col("char_stories").cast(pl.Float64) - pl.col("quality_estimated_floors")).abs()
                <= 1.0
            )
        )
        out = out.with_columns(
            (
                (pl.col("char_category").cast(pl.String).str.to_uppercase() == "MULTI FAMILY")
                & (pl.col("char_beds").cast(pl.Float64, strict=False).fill_null(0) <= 0)
                & (pl.col("char_baths").cast(pl.Float64, strict=False).fill_null(0) <= 0)
                & (pl.col("bldg_footprint_sqft").fill_null(0) >= _MIN_FOOTPRINT_SQFT)
                & supported_multistory
                & (
                    pl.col("quality_livable_to_gross_ratio").fill_null(float("inf"))
                    < _MAX_LIVABLE_TO_GROSS_RATIO
                )
            ).alias("quality_multifamily_area_conflict")
        )

    return out.with_columns(
        (
            pl.col("quality_open_change_of_occupancy").fill_null(False)
            | pl.col("quality_multifamily_area_conflict").fill_null(False)
        ).alias("record_quality_low")
    )
