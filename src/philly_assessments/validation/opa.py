"""Assessment screen: model-vs-OPA disagreement for every residential property
and every residential condo unit.

This is the project's motivating deliverable. Every property in scope is
featurized at a valuation date, priced, given a 90% predictive interval, and
compared against its current OPA market value:

    over_assessed_candidate   OPA value above the 90% predictive interval
    under_assessed_candidate  OPA value below the interval
    within_range              OPA value inside the interval
    no_assessment             OPA value missing/zero — nothing to compare

Two model families share the mart, distinguished by `model_family` +
`interval_method`:

    residential  non-condo SINGLE FAMILY / MULTI FAMILY parcels; point
                 estimate from the latest LightGBM baseline run, interval from
                 the latest Bayesian run's posterior predictive
                 (interval_method="bayesian_posterior")
    condo        88-prefix residential condo units (250-12,000 sqft); point
                 estimate from the latest condo LightGBM run, interval from
                 spatially weighted conformal offsets around it
                 (interval_method="conformal_knn") — the condo model has no
                 Bayesian arm

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
        pl.col("model_median") > 0
    )
    flag = (
        pl.when(~has_assessment)
        .then(pl.lit("no_assessment"))
        .when(pl.col("opa_market_value") > pl.col("model_pi_high_90"))
        .then(pl.lit("over_assessed_candidate"))
        .when(pl.col("opa_market_value") < pl.col("model_pi_low_90"))
        .then(pl.lit("under_assessed_candidate"))
        .otherwise(pl.lit("within_range"))
    )
    screen_z = (
        pl.when(has_assessment)
        .then(
            (pl.col("opa_market_value").log() - pl.col("model_median").log())
            / ((pl.col("model_pi_high_90") / pl.col("model_pi_low_90")).log() / _Z_SCALE)
        )
        .alias("screen_z")
    )
    return (
        df.with_columns(
            flag.alias("assessment_flag"),
            screen_z,
            (pl.col("opa_market_value") / pl.col("model_median")).alias("opa_vs_model_ratio"),
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

    optional = {}
    for name in ("parcels", "demolitions", "delinquencies"):
        path = root / "staged" / f"{name}.parquet"
        optional[name] = pl.scan_parquet(path) if path.exists() else None
    features = assemble_assessment_features(
        pl.scan_parquet(paths["opa"]),
        pl.scan_parquet(paths["sales"]),
        pl.scan_parquet(paths["permits"]),
        pl.scan_parquet(paths["violations"]),
        valuation_date,
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
        optional["parcels"],
        optional["demolitions"],
        optional["delinquencies"],
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
    # models trained on an older feature mart are incoherent with fresh
    # features (e.g. relearned market-area labels shift under the model)
    mart_built = read_derived_manifest(root / "marts" / "sale_features.parquet").built_at
    for run_dir in (baseline_run, bayesian_run):
        run_manifest = read_derived_manifest(run_dir / "run.parquet")
        if run_manifest.built_at < mart_built:
            logger.warning(
                "%s predates the current sale_features mart (%s < %s): retrain before "
                "trusting this screen",
                run_dir.name,
                run_manifest.built_at,
                mart_built,
            )
    pred_lgb = score_lightgbm(baseline_run, features)
    if run_params(baseline_run).get("time_adjusted"):
        # ref-month estimates -> valuation-date estimates
        pred_lgb = pred_lgb * np.exp(-features["time_adj_log"].to_numpy())
    calibration = lightgbm_median_ratio(baseline_run)
    median, lo, hi = score_bayesian_intervals(bayesian_run, features, chunk_size=chunk_size)

    residential = features.select(
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
        "shp_n_linked_parcels",
        "shp_linked_lot_area_m2",
        "dist_tax_delinquent",
        "opa_market_value",
    ).with_columns(
        pl.Series("pred_lightgbm", pred_lgb),
        pl.Series("pred_lightgbm_calibrated", pred_lgb / calibration),
        pl.Series("model_median", median),
        pl.Series("model_pi_low_90", lo),
        pl.Series("model_pi_high_90", hi),
        pl.lit("residential").alias("model_family"),
        pl.lit("bayesian_posterior").alias("interval_method"),
        pl.lit(valuation_date).alias("valuation_date"),
    )

    frames = [residential]
    condo_runs: list[Path] = []
    condo = _condo_screen_frame(root, data_dir, valuation_date, paths, mart_built)
    if condo is not None:
        frame, condo_run = condo
        frames.append(frame)
        condo_runs.append(condo_run)
    screen = finalize_screen(pl.concat(frames, how="diagonal"))

    inputs = []
    for run_dir in (baseline_run, bayesian_run, *condo_runs):
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
        f"{row['model_family']}/{row['assessment_flag']}": row["len"]
        for row in screen.group_by("model_family", "assessment_flag").agg(pl.len()).to_dicts()
    }
    return ScreenResult(path=path, manifest=manifest, flag_counts=flag_counts)


def _condo_screen_frame(
    root: Path,
    data_dir: Path | None,
    valuation_date: datetime,
    paths: dict[str, Path],
    residential_mart_built: datetime,
) -> tuple[pl.DataFrame, Path] | None:
    """Condo rows for the screen, or None when the condo model isn't built.

    Point estimate from the latest condo LightGBM run; 90% interval from
    spatially weighted conformal offsets calibrated on the run's validation
    slice (models/conformal.py) — frame-invariant log offsets, so they apply
    at the valuation date exactly like the prediction."""
    from philly_assessments.features.condo_features import assemble_condo_assessment_features
    from philly_assessments.models.conformal import (
        calibration_from_run,
        conformal_offsets,
        xy_district,
    )

    try:
        condo_run = latest_run_dir("condo", data_dir)
    except FileNotFoundError:
        logger.info("no condo run found; screening residential only")
        return None
    condo_mart = root / "marts" / "condo_sale_features.parquet"
    if not condo_mart.exists():
        logger.info("condo mart missing; screening residential only")
        return None
    condo_run_built = read_derived_manifest(condo_run / "run.parquet").built_at
    for name, built in (
        ("condo_sale_features", read_derived_manifest(condo_mart).built_at),
        ("sale_features", residential_mart_built),
    ):
        if condo_run_built < built:
            logger.warning(
                "%s predates the current %s mart (%s < %s): retrain before "
                "trusting condo screen rows",
                condo_run.name,
                name,
                condo_run_built,
                built,
            )

    features = assemble_condo_assessment_features(
        pl.scan_parquet(paths["opa"]),
        pl.scan_parquet(paths["sales"]),
        valuation_date,
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
    )
    logger.info("scoring %s residential condo units", f"{features.height:,}")
    features_path, _ = write_derived_table(
        features,
        root,
        "marts",
        "condo_assessment_features",
        [],
        notes=f"valuation_date={valuation_date:%Y-%m-%d}",
    )
    logger.info("condo assessment features persisted -> %s", features_path)

    pred = score_lightgbm(condo_run, features)
    if run_params(condo_run).get("time_adjusted"):
        pred = pred * np.exp(
            -features["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
        )
    condo_calibration = lightgbm_median_ratio(condo_run, model="condo_lightgbm")
    cal = calibration_from_run(condo_run, data_dir)
    xy, district = xy_district(features)
    lo_off, hi_off = conformal_offsets(cal, xy, district, method="knn")

    frame = features.select(
        "parcel_id",
        pl.concat_str(
            [pl.col("address"), pl.col("unit").fill_null("")], separator=" #"
        ).alias("address"),
        "char_category",
        pl.col("char_unit_area").alias("char_livable_area"),
        "char_year_built",
        "char_interior_condition",
        "loc_zip5",
        "loc_ward",
        "mkt_bldg_roll_n",
        "bldg_n_units",
        "opa_market_value",
    ).with_columns(
        pl.Series("pred_lightgbm", pred),
        pl.Series("pred_lightgbm_calibrated", pred / condo_calibration),
        # the conformal residuals are measured around the isotonic-calibrated
        # prediction, so that prediction anchors the interval and the flags
        pl.Series("model_median", pred),
        pl.Series("model_pi_low_90", pred * np.exp(lo_off)),
        pl.Series("model_pi_high_90", pred * np.exp(hi_off)),
        pl.lit("condo").alias("model_family"),
        pl.lit("conformal_knn").alias("interval_method"),
        pl.lit(valuation_date).alias("valuation_date"),
    )
    return frame, condo_run
