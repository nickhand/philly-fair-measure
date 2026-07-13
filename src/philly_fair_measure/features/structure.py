"""Current-only structural measurements independent of OPA characteristics."""

from __future__ import annotations

import polars as pl

STRUCTURE_COLUMNS = (
    "char_footprint_sqft",
    "char_footprint_estimated_floors",
    "char_footprint_gross_sqft",
    "char_livable_to_footprint_gross_ratio",
    "char_footprint_story_gap",
    "char_area_conflict",
    "mkt_knn_footprint_price_anchor_log",
)


def add_building_structure_features(
    frame: pl.DataFrame, footprints: pl.LazyFrame | None
) -> pl.DataFrame:
    """Join footprint/height evidence and expose disagreement to the model.

    Footprint height is an independent, imperfect measurement. We preserve
    both it and OPA's living area rather than overwriting either. A production
    mean-model ablation rejected these fields, so they remain diagnostic and
    the explicit conflict flag enters Bayesian uncertainty instead. All fields
    are ``char_*`` because the footprint snapshot is current-only and has the
    same historical-leakage limitation as today's OPA characteristics.
    """
    if footprints is None:
        return frame.with_columns(
            *[
                pl.lit(None, dtype=pl.Float64).alias(column)
                for column in STRUCTURE_COLUMNS
                if column != "char_area_conflict"
            ],
            pl.lit(0.0).alias("char_area_conflict"),
        )

    fp = footprints.select(
        "parcel_id",
        pl.col("bldg_footprint_sqft").cast(pl.Float64).alias("char_footprint_sqft"),
        pl.col("bldg_approx_height_ft").cast(pl.Float64).alias("_footprint_height"),
    ).collect()
    out = frame.join(fp, on="parcel_id", how="left")
    out = out.with_columns(
        (pl.col("_footprint_height") / 10.0)
        .round(0)
        .clip(1.0, 6.0)
        .alias("char_footprint_estimated_floors")
    ).with_columns(
        (pl.col("char_footprint_sqft") * pl.col("char_footprint_estimated_floors")).alias(
            "char_footprint_gross_sqft"
        ),
        (pl.col("char_stories").cast(pl.Float64) - pl.col("char_footprint_estimated_floors")).alias(
            "char_footprint_story_gap"
        ),
    )
    out = out.with_columns(
        pl.when(pl.col("char_footprint_gross_sqft") > 0)
        .then(pl.col("char_livable_area").cast(pl.Float64) / pl.col("char_footprint_gross_sqft"))
        .alias("char_livable_to_footprint_gross_ratio")
    )
    corroborated_stories = (
        pl.col("char_stories").cast(pl.Float64).is_between(2.0, 6.0)
        & (pl.col("char_footprint_estimated_floors") >= 2.0)
        & (pl.col("char_footprint_story_gap").abs() <= 1.0)
    )
    out = out.with_columns(
        (
            (pl.col("char_category").cast(pl.String).str.to_uppercase() == "MULTI FAMILY")
            & (pl.col("char_beds").cast(pl.Float64, strict=False).fill_null(0) <= 0)
            & (pl.col("char_baths").cast(pl.Float64, strict=False).fill_null(0) <= 0)
            & corroborated_stories
            & (pl.col("char_footprint_sqft").fill_null(0) >= 200.0)
            & (pl.col("char_livable_to_footprint_gross_ratio").fill_null(float("inf")) < 0.4)
        )
        .cast(pl.Float64)
        .alias("char_area_conflict"),
        pl.when(
            pl.col("mkt_knn_log_ppsf").is_not_null() & (pl.col("char_footprint_gross_sqft") > 0)
        )
        .then(pl.col("mkt_knn_log_ppsf") + pl.col("char_footprint_gross_sqft").log())
        .alias("mkt_knn_footprint_price_anchor_log"),
    )
    return out.drop("_footprint_height")
