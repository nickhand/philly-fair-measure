"""Auditable property-state and entity-grain evidence features.

The valuation target is an as-is property, not an abstract row in OPA's
table.  A row can describe a stable home, a distressed shell, active work, or
recently completed rehabilitation; one parcel can also represent several tax
accounts or an owner-linked assemblage.  Those are distinct latent states and
entity grains even when their raw columns look superficially similar.

This module compresses the dated/raw evidence into bounded *evidence scores*
and explicit entity ratios.  The scores are intentionally not called
probabilities: they are transparent noisy-OR summaries whose weights encode
the relative strength of public-record evidence.  They never use sale price,
OPA market value, owner identity, or demographic data.  A valuation model may
consume them only after the out-of-time challenger gate.
"""

from __future__ import annotations

from typing import Final

import polars as pl

ENTITY_NUMERIC_FEATURES: Final = (
    "entity_account_count",
    "entity_brt_count",
    "entity_linked_parcel_count",
    "entity_multi_account",
    "entity_multi_brt",
    "entity_assemblage",
    "entity_livable_area_per_account",
    "entity_lot_area_per_account",
    "entity_footprint_area_per_account",
    "entity_multifamily_zero_unit_conflict",
)

PROPERTY_STATE_NUMERIC_FEATURES: Final = (
    "state_active_work_evidence",
    "state_distress_evidence",
    "state_completed_reno_evidence",
    "state_measurement_conflict_evidence",
    "state_transition_evidence",
    "state_competing_evidence",
)

PROPERTY_STATE_CATEGORICAL_FEATURES: Final = ("state_primary_evidence",)
ENTITY_STATE_NUMERIC_FEATURES: Final = (
    *ENTITY_NUMERIC_FEATURES,
    *PROPERTY_STATE_NUMERIC_FEATURES,
)
ENTITY_STATE_CATEGORICAL_FEATURES: Final = PROPERTY_STATE_CATEGORICAL_FEATURES


def _number(column: str, *, default: float = 0.0) -> pl.Expr:
    return pl.col(column).cast(pl.Float64, strict=False).fill_null(default)


def _saturating_count(column: str, scale: float = 1.0) -> pl.Expr:
    """Map a non-negative count to [0, 1) without arbitrary hard cutoffs."""
    return 1.0 - (-_number(column).clip(lower_bound=0.0) / scale).exp()


def _condition_evidence(column: str) -> pl.Expr:
    value = pl.col(column).cast(pl.String)
    return (
        pl.when(value == "7")
        .then(0.98)
        .when(value == "6")
        .then(0.90)
        .when(value == "5")
        .then(0.25)
        .otherwise(0.0)
    )


def _presence(column: str) -> pl.Expr:
    return (_number(column) > 0).cast(pl.Float64)


def _noisy_or(*evidence: pl.Expr) -> pl.Expr:
    complement = pl.lit(1.0)
    for item in evidence:
        complement = complement * (1.0 - item.clip(0.0, 1.0))
    return (1.0 - complement).clip(0.0, 1.0)


def _ensure(frame: pl.DataFrame) -> pl.DataFrame:
    numeric = {
        "shp_parcel_num_accounts",
        "shp_parcel_num_brt",
        "shp_n_linked_parcels",
        "char_livable_area",
        "char_lot_area",
        "char_footprint_sqft",
        "char_beds",
        "char_baths",
        "evt_n_active_change_occupancy_at_sale",
        "evt_n_active_reno_permits_at_sale",
        "evt_n_active_permits_at_sale",
        "evt_n_completed_reno_permits_5y_before",
        "evt_n_open_severe_at_sale",
        "evt_n_severe_violations_5y_before",
        "evt_n_vacant_complaints_5y_before",
        "evt_n_demolitions_before",
        "dist_sheriff_sale",
        "dist_tax_delinquent",
        "quality_characteristic_conflict_score",
        "char_area_conflict",
        "char_new_build",
    }
    strings = {
        "char_category",
        "char_interior_condition",
        "char_exterior_condition",
    }
    expressions = [
        pl.lit(None, dtype=pl.Float64).alias(column)
        for column in sorted(numeric - set(frame.columns))
    ]
    expressions.extend(
        pl.lit(None, dtype=pl.String).alias(column)
        for column in sorted(strings - set(frame.columns))
    )
    return frame.with_columns(*expressions) if expressions else frame


def add_property_state_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Attach entity-grain ratios and bounded property-state evidence.

    Inputs are already temporalized in the sale/assessment feature builders:
    ``evt_*_at_sale`` means as-of the sale for training rows and as-of the
    valuation date for roll-scoring rows.  Current-only condition and
    delinquency evidence retains the documented ``char_``/``dist_`` caveat.
    """
    out = _ensure(frame)

    accounts = pl.max_horizontal(_number("shp_parcel_num_accounts"), pl.lit(1.0))
    brt = pl.max_horizontal(_number("shp_parcel_num_brt"), pl.lit(1.0))
    linked = _number("shp_n_linked_parcels").clip(lower_bound=0.0)
    is_multifamily = pl.col("char_category").cast(pl.String).str.to_uppercase() == "MULTI FAMILY"
    zero_units = (_number("char_beds") <= 0) & (_number("char_baths") <= 0)

    active = _noisy_or(
        0.98 * _presence("evt_n_active_change_occupancy_at_sale"),
        0.85 * _saturating_count("evt_n_active_reno_permits_at_sale", 1.0),
        0.45 * _saturating_count("evt_n_active_permits_at_sale", 2.0),
    )
    distress = _noisy_or(
        _condition_evidence("char_interior_condition"),
        _condition_evidence("char_exterior_condition"),
        0.85 * _saturating_count("evt_n_open_severe_at_sale", 1.0),
        0.55 * _saturating_count("evt_n_severe_violations_5y_before", 2.0),
        0.70 * _saturating_count("evt_n_vacant_complaints_5y_before", 1.0),
        0.90 * _presence("dist_sheriff_sale"),
        0.85 * _saturating_count("evt_n_demolitions_before", 1.0),
        0.20 * _presence("dist_tax_delinquent"),
    )
    rehabilitated_condition = pl.max_horizontal(
        (pl.col("char_interior_condition").cast(pl.String) == "2").cast(pl.Float64),
        (pl.col("char_exterior_condition").cast(pl.String) == "2").cast(pl.Float64),
    )
    completed = _noisy_or(
        0.75 * rehabilitated_condition,
        0.65 * _saturating_count("evt_n_completed_reno_permits_5y_before", 1.0),
        0.50 * _presence("char_new_build"),
    )
    measurement = pl.max_horizontal(
        (_number("quality_characteristic_conflict_score") / 2.0).clip(0.0, 1.0),
        _presence("char_area_conflict"),
        (is_multifamily & zero_units).cast(pl.Float64),
    )
    transition = pl.max_horizontal(active, completed)
    # Multiple strong, contradictory states are themselves useful evidence:
    # e.g. OPA says rehabilitated while L&I says an active gut conversion.
    competing = pl.max_horizontal(
        pl.min_horizontal(active, distress),
        pl.min_horizontal(active, completed),
        pl.min_horizontal(distress, completed),
    )

    out = out.with_columns(
        accounts.alias("entity_account_count"),
        brt.alias("entity_brt_count"),
        linked.alias("entity_linked_parcel_count"),
        (accounts > 1).cast(pl.Float64).alias("entity_multi_account"),
        (brt > 1).cast(pl.Float64).alias("entity_multi_brt"),
        (linked > 0).cast(pl.Float64).alias("entity_assemblage"),
        (_number("char_livable_area") / accounts).alias("entity_livable_area_per_account"),
        (_number("char_lot_area") / accounts).alias("entity_lot_area_per_account"),
        (_number("char_footprint_sqft") / accounts).alias("entity_footprint_area_per_account"),
        (is_multifamily & zero_units)
        .cast(pl.Float64)
        .alias("entity_multifamily_zero_unit_conflict"),
        active.alias("state_active_work_evidence"),
        distress.alias("state_distress_evidence"),
        completed.alias("state_completed_reno_evidence"),
        measurement.alias("state_measurement_conflict_evidence"),
        transition.alias("state_transition_evidence"),
        competing.alias("state_competing_evidence"),
    )
    return out.with_columns(
        pl.when(pl.col("state_active_work_evidence") >= 0.50)
        .then(pl.lit("active_work"))
        .when(pl.col("state_distress_evidence") >= 0.50)
        .then(pl.lit("distressed"))
        .when(pl.col("state_completed_reno_evidence") >= 0.50)
        .then(pl.lit("completed_renovation"))
        .otherwise(pl.lit("stable_or_unknown"))
        .alias("state_primary_evidence")
    )
