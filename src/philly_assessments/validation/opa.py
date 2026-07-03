"""Assessment screen: model-vs-OPA disagreement for every residential property.

This is the project's motivating deliverable. Every residential parcel is
featurized at a valuation date, priced by the latest LightGBM run (with a
transparent global median-ratio calibration) and by the latest Bayesian run
(posterior-predictive median + 90% interval), then compared against its
current OPA market value:

    over_assessed_candidate   OPA value above the 90% predictive interval
    under_assessed_candidate  OPA value below the interval
    within_range              OPA value inside the interval
    no_assessment             OPA value missing/zero — nothing to compare

`screen_z` expresses the disagreement in predictive-uncertainty units
(log(OPA/median) scaled by the interval's log-width / 3.29, i.e. ~standard
normal if the predictive distribution is right), so properties are ranked by
how confidently the model disagrees — not just by raw dollar gap. Interpret
candidates as *screening leads for comp-level review*, not verdicts: the
models inherit every current_only characteristics caveat documented in
docs/features.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config
from philly_assessments.features.assessment_features import assemble_assessment_features
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest
from philly_assessments.models.scoring import (
    latest_run_dir,
    lightgbm_median_ratio,
    run_params,
    score_bayesian_intervals,
    score_lightgbm,
)

logger = logging.getLogger(__name__)

_Z_SCALE = 3.29  # log-width of a 90% interval in standard-normal units (2 * 1.645)


def finalize_screen(df: pl.DataFrame) -> pl.DataFrame:
    """Pure classification/ranking step; expects prediction columns to be present."""
    has_assessment = (pl.col("opa_market_value").fill_null(0) > 0) & (
        pl.col("bayes_median") > 0
    )
    flag = (
        pl.when(~has_assessment)
        .then(pl.lit("no_assessment"))
        .when(pl.col("opa_market_value") > pl.col("bayes_pi_high_90"))
        .then(pl.lit("over_assessed_candidate"))
        .when(pl.col("opa_market_value") < pl.col("bayes_pi_low_90"))
        .then(pl.lit("under_assessed_candidate"))
        .otherwise(pl.lit("within_range"))
    )
    screen_z = (
        pl.when(has_assessment)
        .then(
            (pl.col("opa_market_value").log() - pl.col("bayes_median").log())
            / ((pl.col("bayes_pi_high_90") / pl.col("bayes_pi_low_90")).log() / _Z_SCALE)
        )
        .alias("screen_z")
    )
    return (
        df.with_columns(
            flag.alias("assessment_flag"),
            screen_z,
            (pl.col("opa_market_value") / pl.col("bayes_median")).alias("opa_vs_bayes_ratio"),
            (pl.col("opa_market_value") / pl.col("pred_lightgbm_calibrated")).alias(
                "opa_vs_lightgbm_ratio"
            ),
        )
        .with_columns(pl.col("screen_z").abs().alias("screen_abs_z"))
        .sort("screen_abs_z", descending=True, nulls_last=True)
    )


@dataclass(frozen=True)
class ScreenResult:
    path: Path
    manifest: DerivedManifest
    flag_counts: dict[str, int]


def build_assessment_screen(
    data_dir: Path | None = None,
    *,
    valuation_date: datetime | None = None,
    chunk_size: int = 50_000,
) -> ScreenResult:
    root = data_dir if data_dir is not None else config.data_dir()
    if valuation_date is None:
        valuation_date = datetime.now(UTC).replace(tzinfo=None, hour=0, minute=0, second=0,
                                                   microsecond=0)
    paths = {
        "opa": root / "staged" / "opa_properties.parquet",
        "sales": root / "marts" / "sale_validity.parquet",
        "permits": root / "staged" / "permits.parquet",
        "violations": root / "staged" / "violations.parquet",
        "market_areas": root / "marts" / "market_areas.parquet",
        "price_index": root / "marts" / "price_index.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run the pipeline first")

    features = assemble_assessment_features(
        pl.scan_parquet(paths["opa"]),
        pl.scan_parquet(paths["sales"]),
        pl.scan_parquet(paths["permits"]),
        pl.scan_parquet(paths["violations"]),
        valuation_date,
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
    )
    logger.info("scoring %s residential properties", f"{features.height:,}")
    # persist the full feature frame: the comps CLI prices arbitrary parcels
    # from it without re-running feature assembly (models/comps.py)
    features_path, _ = write_derived_table(
        features,
        root,
        "marts",
        "assessment_features",
        [],
        notes=f"valuation_date={valuation_date:%Y-%m-%d}",
    )
    logger.info("assessment features persisted -> %s", features_path)

    baseline_run = latest_run_dir("baseline", data_dir)
    bayesian_run = latest_run_dir("bayesian", data_dir)
    pred_lgb = score_lightgbm(baseline_run, features)
    if run_params(baseline_run).get("time_adjusted"):
        # ref-month estimates -> valuation-date estimates
        pred_lgb = pred_lgb * np.exp(-features["time_adj_log"].to_numpy())
    calibration = lightgbm_median_ratio(baseline_run)
    median, lo, hi = score_bayesian_intervals(bayesian_run, features, chunk_size=chunk_size)

    screen = finalize_screen(
        features.select(
            "parcel_id",
            "address",
            "char_category",
            "char_livable_area",
            "char_year_built",
            "char_interior_condition",
            "loc_zip5",
            "loc_ward",
            "mkt_block_roll_n",
            "mkt_parcel_prev_price",
            "mkt_parcel_days_since_prev",
            "opa_market_value",
        ).with_columns(
            pl.Series("pred_lightgbm", pred_lgb),
            pl.Series("pred_lightgbm_calibrated", pred_lgb / calibration),
            pl.Series("bayes_median", median),
            pl.Series("bayes_pi_low_90", lo),
            pl.Series("bayes_pi_high_90", hi),
            pl.lit(valuation_date).alias("valuation_date"),
        )
    )

    inputs = []
    for run_dir in (baseline_run, bayesian_run):
        manifest = read_derived_manifest(run_dir / "run.parquet")
        inputs.append(
            InputRef(dataset=f"models/{manifest.table}", fetched_at=manifest.built_at.isoformat())
        )
    for path in paths.values():
        manifest = read_derived_manifest(path)
        inputs.append(
            InputRef(
                dataset=f"{manifest.layer}/{manifest.table}",
                fetched_at=manifest.built_at.isoformat(),
            )
        )
    path, manifest = write_derived_table(
        screen,
        root,
        "marts",
        "assessment_screen",
        inputs,
        notes=f"valuation_date={valuation_date:%Y-%m-%d}; lightgbm calibration={calibration:.4f}",
    )
    flag_counts = {
        row["assessment_flag"]: row["len"]
        for row in screen.group_by("assessment_flag").agg(pl.len()).to_dicts()
    }
    return ScreenResult(path=path, manifest=manifest, flag_counts=flag_counts)
