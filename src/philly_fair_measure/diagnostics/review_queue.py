"""Stratified human-review queue for active model/data-quality learning.

The queue is not a valuation feature and cannot change an estimate.  It ranks
where a verified field inspection or record correction would teach us most,
then caps selection within district × model-value quintile strata so audit
attention does not collapse onto Center City, expensive homes, or the largest
raw dollar gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef, read_derived_manifest


@dataclass(frozen=True)
class ReviewQueueResult:
    path: Path
    frame: pl.DataFrame


def _reason_expr() -> pl.Expr:
    return pl.concat_list(
        pl.when(pl.col("quality_zero_bed_bath_conflict").fill_null(False)).then(
            pl.lit("zero_bed_bath_conflict")
        ),
        pl.when(pl.col("quality_area_outlier").fill_null(False)).then(
            pl.lit("extreme_area_conflict")
        ),
        pl.when(pl.col("quality_characteristic_outlier").fill_null(False)).then(
            pl.lit("joint_characteristic_outlier")
        ),
        pl.when(pl.col("state_active_work_evidence").fill_null(0.0) >= 0.5).then(
            pl.lit("active_work")
        ),
        pl.when(pl.col("state_distress_evidence").fill_null(0.0) >= 0.5).then(pl.lit("distress")),
        pl.when(pl.col("state_competing_evidence").fill_null(0.0) >= 0.25).then(
            pl.lit("competing_state_evidence")
        ),
        pl.when(pl.col("prediction_risk_tier") == "high").then(pl.lit("high_prediction_risk")),
        pl.when(pl.col("assessment_flag") == "insufficient_record").then(
            pl.lit("verdict_withheld")
        ),
    ).list.drop_nulls()


def build_review_queue_frame(screen: pl.DataFrame, *, limit: int = 2_000) -> pl.DataFrame:
    """Build a geographically/value-stratified review queue.

    Priority uses relative disagreement and expected error, never raw dollar
    gap, owner identity, or demographics.  At least one row per non-empty
    stratum can enter before a second row from the same stratum.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    frame = screen.filter(pl.col("model_family") == "residential").with_columns(
        pl.col("prediction_risk_score").cast(pl.Float64).fill_nan(0.0).fill_null(0.0),
        pl.col("quality_characteristic_conflict_score")
        .cast(pl.Float64)
        .fill_nan(0.0)
        .fill_null(0.0),
        pl.col("state_competing_evidence").cast(pl.Float64).fill_nan(0.0).fill_null(0.0),
        pl.col("state_transition_evidence").cast(pl.Float64).fill_nan(0.0).fill_null(0.0),
    )
    # Model-value quintiles, not observed sale-price quintiles: this works on
    # the full roll and avoids using a future outcome.
    value = frame["display_median"].cast(pl.Float64).to_numpy()
    finite = value[np.isfinite(value) & (value > 0)]
    edges = np.quantile(finite, [0.2, 0.4, 0.6, 0.8]) if len(finite) else np.zeros(4)
    value_quintile = np.digitize(np.nan_to_num(value, nan=0.0), edges) + 1
    frame = frame.with_columns(pl.Series("review_value_quintile", value_quintile))

    relative_gap = (
        ((pl.col("opa_market_value").cast(pl.Float64) / pl.col("display_median")).log().abs())
        .fill_nan(0.0)
        .fill_null(0.0)
        .clip(0.0, 1.5)
    )
    conflict = (pl.col("quality_characteristic_conflict_score") / 2.0).clip(0.0, 1.0)
    state = pl.max_horizontal(
        pl.col("state_competing_evidence"), pl.col("state_transition_evidence") * 0.5
    )
    # Multiplicative interaction: a high-risk estimate becomes more valuable
    # to audit when records/states disagree. The additive gap term still lets
    # a large model-vs-OPA disagreement enter without favoring high dollar
    # properties. This score only orders audits; it never trains valuation.
    priority = (
        pl.col("prediction_risk_score") * (1.0 + conflict + state) + 0.20 * relative_gap
    ).alias("review_priority")
    frame = frame.with_columns(priority, _reason_expr().alias("review_reasons")).filter(
        (pl.col("review_priority") > 0) & (pl.col("review_reasons").list.len() > 0)
    )
    district = pl.col("loc_district").cast(pl.String).fill_null("unknown")
    frame = frame.with_columns(
        pl.concat_str(
            [district, pl.col("review_value_quintile").cast(pl.String)], separator="/q"
        ).alias("review_stratum")
    ).with_columns(
        pl.col("review_priority")
        .rank(method="ordinal", descending=True)
        .over("review_stratum")
        .alias("review_rank_within_stratum"),
        pl.col("review_priority")
        .rank(method="ordinal", descending=True)
        .alias("review_rank_citywide"),
    )
    # Round-robin behavior via rank-first ordering: every stratum's #1 comes
    # before any stratum's #2; priority breaks ties within each round.
    return (
        frame.sort(
            "review_rank_within_stratum",
            "review_priority",
            descending=[False, True],
        )
        .head(limit)
        .with_columns(
            pl.col("quality_expected_livable_area").fill_nan(None),
            pl.col("quality_area_reference_low_90").fill_nan(None),
            pl.col("quality_area_reference_high_90").fill_nan(None),
            pl.col("quality_expected_beds").fill_nan(None),
            pl.col("quality_expected_baths").fill_nan(None),
            pl.col("quality_characteristic_conflict_score").fill_nan(None),
        )
        .select(
            "parcel_id",
            "address",
            "loc_district",
            "review_value_quintile",
            "review_stratum",
            "review_rank_within_stratum",
            "review_rank_citywide",
            "review_priority",
            "review_reasons",
            "display_median",
            "display_pi_low_90",
            "display_pi_high_90",
            "opa_market_value",
            "assessment_flag",
            "prediction_risk_score",
            "prediction_risk_tier",
            "char_livable_area",
            "char_beds",
            "char_baths",
            "quality_expected_livable_area",
            "quality_area_reference_low_90",
            "quality_area_reference_high_90",
            "quality_expected_beds",
            "quality_expected_baths",
            "quality_characteristic_conflict_score",
            "state_primary_evidence",
        )
    )


def build_review_queue(data_dir: Path | None = None, *, limit: int = 2_000) -> ReviewQueueResult:
    root = data_dir if data_dir is not None else config.data_dir()
    screen_path = root / "marts" / "assessment_screen.parquet"
    if not screen_path.exists():
        raise FileNotFoundError(f"{screen_path} missing; run `fair-measure screen-assessments`")
    screen = pl.read_parquet(screen_path)
    feature_path = root / "marts" / "assessment_features.parquet"
    inputs: list[InputRef] = []
    if "loc_district" not in screen.columns:
        if not feature_path.exists():
            raise FileNotFoundError(
                f"{feature_path} missing; district-stratified review queue cannot be built"
            )
        screen = screen.join(
            pl.read_parquet(feature_path).select("parcel_id", "loc_district"),
            on="parcel_id",
            how="left",
        )
        feature_manifest = read_derived_manifest(feature_path)
        inputs.append(
            InputRef(
                dataset=f"{feature_manifest.layer}/{feature_manifest.table}",
                fetched_at=feature_manifest.built_at.isoformat(),
            )
        )
    frame = build_review_queue_frame(screen, limit=limit)
    manifest = read_derived_manifest(screen_path)
    inputs.append(
        InputRef(
            dataset=f"{manifest.layer}/{manifest.table}",
            fetched_at=manifest.built_at.isoformat(),
        )
    )
    path, _ = write_derived_table(
        frame,
        root,
        "diagnostics",
        "review_queue",
        inputs,
        notes=(
            "stratified active-review queue; relative gaps only; no owner or demographic data; "
            "never a valuation feature"
        ),
    )
    return ReviewQueueResult(path, frame)
