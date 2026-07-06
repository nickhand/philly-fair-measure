"""Assessment screen: model-vs-OPA disagreement for every residential property
and every residential condo unit.

This is the project's motivating deliverable. Every property in scope is
featurized at a valuation date, priced, given a 90% predictive interval, and
compared against its current OPA market value:

    over_assessed_candidate   OPA value above the 90% predictive interval
    under_assessed_candidate  OPA value below the interval
    within_range              OPA value inside the interval
    no_assessment             OPA value missing/zero — nothing to compare
    insufficient_record       no recorded living area (usually brand-new
                              construction still being written up) — the
                              model cannot price it, so no verdict

Newly built homes (year built within two years of the valuation date) never
flag "over": comp evidence reflects the older stock they replaced and runs
low, so an over call is not defensible; they land in the attention tier
instead, and the report carries a new-construction caveat (`new_build`).

Two model families share the mart, distinguished by `model_family` +
`interval_method`:

    residential  non-condo SINGLE FAMILY / MULTI FAMILY parcels; point
                 estimate from the latest LightGBM baseline run, interval from
                 the latest Bayesian run's posterior predictive
                 (interval_method="bayesian_posterior")
    condo        88-prefix residential condo units (250-12,000 sqft); point
                 estimate from the latest condo LightGBM run, interval from
                 spatially weighted conformal offsets around that prediction
                 (interval_method="conformal_knn") — the self-consistent
                 pairing; the condo Bayesian arm is a research artifact
                 (hot median, stiff to unit-level evidence)

Residential rows also carry `conformal_pi_low_90`/`conformal_pi_high_90`
(spatially weighted conformal band around the LightGBM point — the frequentist
cross-check) and every row a `display_pi_low_90`/`display_pi_high_90`: the
range both machines support (Bayesian ∩ conformal for residential when that
intersection also contains the median, the native band elsewhere). Surfaces
should show the display band. Residential over/under flags require BOTH
machines to put OPA outside on the same side (the agreement gate in
finalize_screen); `screen_z` stays anchored to `model_pi_*`.

`screen_z` expresses the disagreement in predictive-uncertainty units
(log(OPA/median) scaled by the interval's log-width / 3.29, i.e. ~standard
normal if the predictive distribution is right), so properties are ranked by
how confidently the model disagrees — not just by raw dollar gap. Within-range
rows additionally carry `attention` ("high"/"low"/null) when |screen_z| >
_ATTENTION_Z: the OPA value is still inside the sale-plausibility interval but
in its outer part — surfaced as "worth a closer look", never as a flag. Interpret
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

from philly_fair_measure import config
from philly_fair_measure.features.assessment_features import assemble_assessment_features
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest
from philly_fair_measure.models.scoring import (
    bayesian_median_ratio,
    latest_run_dir,
    lightgbm_median_ratio,
    run_params,
    score_bayesian_intervals,
    score_lightgbm,
)
from philly_fair_measure.vocab import AssessmentFlag, AttentionTier, IntervalMethod, ModelFamily

logger = logging.getLogger(__name__)

_Z_SCALE = 3.29  # log-width of a 90% interval in standard-normal units (2 * 1.645)
# Attention tier: within-range rows whose OPA value sits beyond ~1 predictive
# sd of the model median. Deliberately weaker than a flag (|z| > ~1.645): with
# the median rowhome interval, z=1 still means OPA ~1.7x or ~0.6x our estimate,
# but per-home sale noise keeps it short of a defensible over/under call.
_ATTENTION_Z = 1.0


class StaleRunError(RuntimeError):
    """A scoring run predates the feature mart it would score against."""


_RETRAIN_HINTS = {
    "baseline": "fair-measure train-baseline",
    "bayesian": "fair-measure train-bayesian",
    "retail": "fair-measure train-baseline --market retail",
    "condo": "fair-measure train-condo",
    "bayesian-condo": "fair-measure train-bayesian --family condo",
}


def _require_coherent(
    run_dir: Path,
    marts: tuple[tuple[str, datetime], ...],
    *,
    allow_stale: bool,
) -> None:
    """Refuse to score with a run older than the mart it scores against.

    Rebuilding features (especially relearning market areas) relabels the
    geography a run's effects are indexed by — a stale run then prices ~every
    parcel with some other neighborhood's premium and the screen fills with
    false flags (measured twice: 4x in July 2026 planning, 10x on 2026-07-05).
    `allow_stale` downgrades the refusal to a warning for deliberate use."""
    run_built = read_derived_manifest(run_dir / "run.parquet").built_at
    for name, built in marts:
        if run_built >= built:
            continue
        kind = run_dir.name.removeprefix("run_id=").split("-", 1)[-1]
        hint = _RETRAIN_HINTS.get(kind, "retrain the model")
        message = (
            f"{run_dir.name} predates the current {name} mart "
            f"({run_built} < {built}); its learned geography no longer matches "
            f"the features, so the screen would be full of false flags. "
            f"Retrain first (`{hint}`), or pass --allow-stale to build anyway."
        )
        if not allow_stale:
            raise StaleRunError(message)
        logger.warning("%s (building anyway: --allow-stale)", message)


def finalize_screen(df: pl.DataFrame) -> pl.DataFrame:
    """Pure classification/ranking step; expects prediction columns to be present."""
    has_assessment = (pl.col("opa_market_value").fill_null(0) > 0) & (pl.col("model_median") > 0)
    # Record completeness: a home with no recorded living area cannot be
    # priced — the model takes the zero literally (measured 2026-07-05: $3k
    # medians against $500k assessments, 19 of the top-100 z leads). Usually
    # brand-new construction the city is still writing up; no verdict.
    # (The column guards tolerate minimal test fixtures.)
    insufficient = (
        pl.col("char_livable_area").fill_null(0) <= 0
        if "char_livable_area" in df.columns
        else pl.lit(False)
    )
    # New construction: until the home itself sells, nearby sales mostly
    # reflect the older stock it replaced, so a sale-comparison model runs
    # low (measured: new-build over-flag assessments at 3.2x our medians,
    # with listings agreeing with OPA). An "over" call is not defensible
    # here — it demotes to within-range, where the attention tier picks it
    # up as "worth a look"; the report carries a plain-language caveat.
    # Under-flags stay: a new build the city still prices as the old parcel
    # is a genuine lead. Two-year window: OPA's recorded year wobbles within
    # a single development (202 vs 204/206 Kalos St differ by a year on
    # identical rows), and an unsold two-year-old build is still comp-less.
    new_build = (
        (pl.col("char_year_built").fill_null(0) >= pl.col("valuation_date").dt.year() - 2)
        if {"char_year_built", "valuation_date"}.issubset(df.columns)
        else pl.lit(False)
    )
    # Agreement gate: where a second uncertainty machine exists (residential
    # rows carry a conformal band around the LightGBM point), a flag requires
    # BOTH machines to put OPA outside on the same side. Measured 2026-07-06:
    # the conformal band disputed 30% of Bayesian-only flags (253 over /
    # 1,070 under), concentrated on gentrification-edge blocks where the two
    # arms disagree about the price level — one machine's word is not enough
    # to tell an owner to appeal. Disputed rows land within-range, where the
    # attention tier picks them up (|z| > 1.64 by construction, so every
    # demoted flag surfaces as "worth a look"). Rows without conformal
    # columns (condos, minimal fixtures) gate on their native band alone.
    if {"conformal_pi_low_90", "conformal_pi_high_90"}.issubset(df.columns):
        conformal_agrees_over = pl.col("conformal_pi_high_90").is_null() | (
            pl.col("opa_market_value") > pl.col("conformal_pi_high_90")
        )
        conformal_agrees_under = pl.col("conformal_pi_low_90").is_null() | (
            pl.col("opa_market_value") < pl.col("conformal_pi_low_90")
        )
    else:
        conformal_agrees_over = pl.lit(True)
        conformal_agrees_under = pl.lit(True)
    flag = (
        pl.when(insufficient)
        .then(pl.lit(AssessmentFlag.INSUFFICIENT))
        .when(~has_assessment)
        .then(pl.lit(AssessmentFlag.NONE))
        .when((pl.col("opa_market_value") > pl.col("model_pi_high_90")) & conformal_agrees_over)
        .then(
            pl.when(new_build)
            .then(pl.lit(AssessmentFlag.WITHIN))
            .otherwise(pl.lit(AssessmentFlag.OVER))
        )
        .when((pl.col("opa_market_value") < pl.col("model_pi_low_90")) & conformal_agrees_under)
        .then(pl.lit(AssessmentFlag.UNDER))
        .otherwise(pl.lit(AssessmentFlag.WITHIN))
    )
    screen_z = (
        pl.when(has_assessment & ~insufficient)
        .then(
            (pl.col("opa_market_value").log() - pl.col("model_median").log())
            / ((pl.col("model_pi_high_90") / pl.col("model_pi_low_90")).log() / _Z_SCALE)
        )
        .alias("screen_z")
    )
    unpriceable_null = pl.when(insufficient).then(pl.lit(None, dtype=pl.Float64))
    # Display band: the range BOTH uncertainty machines support. For
    # residential that's the Bayesian posterior ∩ conformal-knn intersection;
    # condo rows (and fixtures without conformal columns) keep their native
    # band. The intersection must also CONTAIN the displayed median — an
    # intersection that excludes it reads as "estimate $996k, range
    # $711k–$797k" (measured 2026-07-06: 28,837 rows). When the intersection
    # fails, two coherent candidates exist: the native posterior band, and the
    # conformal band minimally expanded to include the median. Neither
    # dominates — the posterior's parametric sigma blows up on rare covariate
    # combos (115x on 3416 Sansom St), while expanding the conformal band
    # re-imports the full level gap where the two arms disagree about price
    # level (measured: 384x max if always-conformal). Show whichever is
    # narrower per row. Flags and screen_z stay on model_pi_*; this is
    # presentation-layer truth.
    if {"conformal_pi_low_90", "conformal_pi_high_90"}.issubset(df.columns):
        cross_lo = pl.max_horizontal("model_pi_low_90", "conformal_pi_low_90")
        cross_hi = pl.min_horizontal("model_pi_high_90", "conformal_pi_high_90")
        agree = (
            (cross_lo < cross_hi)
            & (pl.col("model_median") >= cross_lo)
            & (pl.col("model_median") <= cross_hi)
        )
        conf_lo = pl.min_horizontal("conformal_pi_low_90", "model_median")
        conf_hi = pl.max_horizontal("conformal_pi_high_90", "model_median")
        use_conf = (
            pl.col("conformal_pi_low_90").is_not_null()
            & (conf_lo > 0)
            & ((conf_hi / conf_lo) < (pl.col("model_pi_high_90") / pl.col("model_pi_low_90")))
        )
        fallback_lo = pl.when(use_conf).then(conf_lo).otherwise(pl.col("model_pi_low_90"))
        fallback_hi = pl.when(use_conf).then(conf_hi).otherwise(pl.col("model_pi_high_90"))
        display_lo = pl.when(agree).then(cross_lo).otherwise(fallback_lo)
        display_hi = pl.when(agree).then(cross_hi).otherwise(fallback_hi)
    else:
        display_lo = pl.col("model_pi_low_90")
        display_hi = pl.col("model_pi_high_90")
    return (
        df.with_columns(
            display_lo.alias("display_pi_low_90"),
            display_hi.alias("display_pi_high_90"),
            flag.alias("assessment_flag"),
            screen_z,
            new_build.alias("new_build"),
            unpriceable_null.otherwise(pl.col("opa_market_value") / pl.col("model_median")).alias(
                "opa_vs_model_ratio"
            ),
            unpriceable_null.otherwise(
                pl.col("opa_market_value") / pl.col("pred_lightgbm_calibrated")
            ).alias("opa_vs_lightgbm_ratio"),
        )
        .with_columns(pl.col("screen_z").abs().alias("screen_abs_z"))
        .with_columns(
            # attention: inside the interval but in its outer part — "worth a
            # closer look", explicitly weaker language than a flag
            pl.when(
                (pl.col("assessment_flag") == AssessmentFlag.WITHIN)
                & (pl.col("screen_abs_z") > _ATTENTION_Z)
            )
            .then(
                pl.when(pl.col("screen_z") > 0)
                .then(pl.lit(AttentionTier.HIGH))
                .otherwise(pl.lit(AttentionTier.LOW))
            )
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("attention")
        )
        .sort("screen_abs_z", descending=True, nulls_last=True)
    )


def strict_twin_key() -> pl.Expr:
    """Every recorded characteristic, concatenated: two parcels sharing this
    key on the same block are identical per OPA's own records."""
    return pl.concat_str(
        [
            pl.col("loc_block_id"),
            pl.col("char_livable_area").cast(pl.String),
            pl.col("char_lot_area").fill_null(-1).cast(pl.String),
            pl.col("char_style").fill_null("?"),
            pl.col("char_stories").fill_null(-1).cast(pl.String),
            pl.col("char_year_built").fill_null(-1).cast(pl.String),
            pl.col("char_exterior_condition").fill_null("?"),
            pl.col("char_interior_condition").fill_null("?"),
            pl.col("char_quality_grade_raw").fill_null("?"),
            pl.col("char_basement").fill_null("?"),
            pl.col("char_garage_spaces").fill_null(-1).cast(pl.String),
            pl.col("char_central_air").fill_null("?"),
        ],
        separator="|",
    )


def twin_uniformity(features: pl.DataFrame, *, min_set: int = 5) -> pl.DataFrame:
    """Strict identical-twin uniformity stats per parcel (PA uniformity clause).

    ~40% of residential Philadelphia sits in same-block runs of physically
    identical rowhomes. The STRICT key requires every recorded characteristic
    to match — area, lot, style, stories, year built, exterior/interior
    condition, quality grade, basement, garage, central air — so a parcel
    assessed above its twins' median differs in NOTHING OPA's own records
    capture. Measured 2026-07-03: 22.6% of residential parcels sit in strict
    sets of >=5; OPA is uniform on 77% of sets (all-equal assessments,
    median spread 0.0%), and the residue (624 parcels >10% above twin
    median) is the sharpest appeal evidence public data can produce."""
    eligible = features.filter(
        (pl.col("opa_market_value").fill_null(0) > 0)
        & pl.col("loc_block_id").is_not_null()
        & (pl.col("char_livable_area").fill_null(0) > 0)
    ).select("parcel_id", "opa_market_value", strict_twin_key().alias("_twin_key"))
    return (
        eligible.with_columns(pl.len().over("_twin_key").alias("twin_n"))
        .filter(pl.col("twin_n") >= min_set)
        .with_columns(
            (
                pl.col("opa_market_value") / pl.col("opa_market_value").median().over("_twin_key")
            ).alias("opa_vs_twin_median")
        )
        .select("parcel_id", "twin_n", "opa_vs_twin_median")
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
    allow_stale: bool = False,
) -> ScreenResult:
    root = data_dir if data_dir is not None else config.data_dir()
    if valuation_date is None:
        valuation_date = datetime.now(UTC).replace(
            tzinfo=None, hour=0, minute=0, second=0, microsecond=0
        )
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

    # coherence gate BEFORE the expensive feature assembly: models trained on
    # an older feature mart are incoherent with fresh features (relearned
    # market-area labels shift under the model), so refuse fast, not after
    # five minutes of work
    baseline_run = latest_run_dir("baseline", data_dir)
    bayesian_run = latest_run_dir("bayesian", data_dir)
    try:
        retail_run: Path | None = latest_run_dir("retail", data_dir)
    except FileNotFoundError:
        retail_run = None
    mart_built = read_derived_manifest(root / "marts" / "sale_features.parquet").built_at
    for run_dir in (baseline_run, bayesian_run, *([retail_run] if retail_run else [])):
        _require_coherent(run_dir, (("sale_features", mart_built),), allow_stale=allow_stale)

    optional = {}
    for name in (
        "parcels",
        "demolitions",
        "delinquencies",
        "complaints",
        "case_investigations",
        "rental_licenses",
        "appeals",
        "mortgages",
    ):
        path = root / "staged" / f"{name}.parquet"
        optional[name] = pl.scan_parquet(path) if path.exists() else None
    proximity_path = root / "marts" / "proximity.parquet"
    optional["proximity"] = pl.scan_parquet(proximity_path) if proximity_path.exists() else None
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
        optional["proximity"],
        optional["complaints"],
        optional["case_investigations"],
        optional["rental_licenses"],
        optional["appeals"],
        optional["mortgages"],
    )
    # pin row order: interval draws are seeded by row position, and polars
    # joins are not order-stable across runs — without this, borderline
    # parcels flip flags between otherwise-identical builds
    features = features.sort("parcel_id")
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

    pred_lgb = score_lightgbm(baseline_run, features)
    if run_params(baseline_run).get("time_adjusted"):
        # ref-month estimates -> valuation-date estimates
        pred_lgb = pred_lgb * np.exp(-features["time_adj_log"].to_numpy())
    calibration = lightgbm_median_ratio(baseline_run)
    median, lo, hi = score_bayesian_intervals(bayesian_run, features, chunk_size=chunk_size)
    # same published-global-calibration convention as the LightGBM point: the
    # run's out-of-time median ratio divides the whole predictive band (a log
    # shift — width and coverage are untouched, z-scores become centered)
    bayes_calibration = bayesian_median_ratio(bayesian_run)
    median, lo, hi = median / bayes_calibration, lo / bayes_calibration, hi / bayes_calibration

    # second uncertainty machine: spatially weighted conformal offsets around
    # the LightGBM point (models/conformal.py). Residuals are frame-invariant,
    # so offsets learned in the reference frame apply to the valuation-date
    # prediction. The Bayesian band keeps anchoring the flags; this band's job
    # is honesty where the two disagree — the display range is their
    # intersection (finalize_screen), so one arm's blown-up tail can't put a
    # $2.7M ceiling on an $800k rowhome (measured 2026-07-06, 2314 Wallace St:
    # bayesian 254k-2.71M vs conformal-knn 630k-1.65M on the same features)
    from philly_fair_measure.models.conformal import (
        calibration_from_run,
        conformal_offsets,
        xy_district,
    )

    cal = calibration_from_run(baseline_run, data_dir)
    xy, district = xy_district(features)
    conf_lo_off, conf_hi_off = conformal_offsets(cal, xy, district, method="knn")
    log_pred = np.log(pred_lgb)
    conformal_lo = np.exp(log_pred + conf_lo_off)
    conformal_hi = np.exp(log_pred + conf_hi_off)

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
        "evt_n_vacant_complaints_5y_before",
        "evt_vacant_complaint_days_since",
        "evt_n_unpermitted_work_complaints_5y_before",
        "ten_rental_license_at_sale",
        "opa_market_value",
    ).with_columns(
        pl.Series("pred_lightgbm", pred_lgb),
        pl.Series("pred_lightgbm_calibrated", pred_lgb / calibration),
        pl.Series("model_median", median),
        pl.Series("model_pi_low_90", lo),
        pl.Series("model_pi_high_90", hi),
        pl.Series("conformal_pi_low_90", conformal_lo),
        pl.Series("conformal_pi_high_90", conformal_hi),
        pl.lit(ModelFamily.RESIDENTIAL).alias("model_family"),
        pl.lit(IntervalMethod.BAYESIAN).alias("interval_method"),
        pl.lit(valuation_date).alias("valuation_date"),
    )

    residential = residential.join(twin_uniformity(features), on="parcel_id", how="left")

    # both value conventions (docs/equity-diagnostics.md): retail value from a
    # financed-only model, cash-market value via the published channel discount.
    # Optional — added only when a retail run exists; no propensity proxy.
    if retail_run is not None:
        from philly_fair_measure.diagnostics.channel import (
            cash_market_value,
            sale_price_quintile_edges,
        )

        retail = score_lightgbm(retail_run, features)
        if run_params(retail_run).get("time_adjusted"):
            retail = retail * np.exp(-features["time_adj_log"].to_numpy())
        edges = sale_price_quintile_edges(data_dir)
        residential = residential.with_columns(
            pl.Series("retail_value", retail),
            pl.Series("cash_market_value", cash_market_value(retail, edges)),
        )

    # aerial change evidence (diagnostics/aerial_change.py, `philly
    # aerial-score`): joined when present; scores describe the parcel between
    # two flights, so they stay valid across screen rebuilds
    aerial_path = root / "diagnostics" / "aerial_change_scores.parquet"
    if aerial_path.exists():
        residential = residential.join(
            pl.read_parquet(aerial_path).select(
                "parcel_id", "aerial_change_score", "aerial_change_flag", "aerial_pair"
            ),
            on="parcel_id",
            how="left",
        )

    frames = [residential]
    condo_runs: list[Path] = []
    condo = _condo_screen_frame(
        root, data_dir, valuation_date, paths, mart_built, allow_stale=allow_stale
    )
    if condo is not None:
        frame, runs = condo
        frames.append(frame)
        condo_runs.extend(runs)
    screen = finalize_screen(pl.concat(frames, how="diagonal"))
    # structural truths every build must satisfy (the 2026-07-06 review's two
    # bug classes, made unrepeatable): refuse to write a mart that breaks them
    from philly_fair_measure.validation.screen_audit import assert_screen_invariants

    assert_screen_invariants(screen)

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
        notes=(
            f"valuation_date={valuation_date:%Y-%m-%d}; "
            f"lightgbm calibration={calibration:.4f}; "
            f"bayesian calibration={bayes_calibration:.4f}"
        ),
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
    *,
    allow_stale: bool = False,
) -> tuple[pl.DataFrame, list[Path]] | None:
    """Condo rows for the screen, or None when the condo model isn't built.

    Point estimate AND interval from the self-consistent LightGBM + conformal
    pairing: the isotonic-calibrated condo LightGBM (measured 2026-07-06:
    repeat-segment median 1.035 with the prior-sale carry-forward) anchors the
    flags, with spatially weighted conformal offsets calibrated on its own
    validation slice (models/conformal.py). The condo Bayesian arm stays a
    research artifact: its median runs ~25% hot out-of-time (the district
    price index over-adjusts condos) and, being linear, it barely reacts to a
    unit's own prior sale — 3600 Conshohocken #1001 (sold $140k in 2024)
    priced $84k Bayesian vs $118k LightGBM against OPA's $120k."""
    from philly_fair_measure.features.condo_features import assemble_condo_assessment_features

    try:
        condo_run = latest_run_dir("condo", data_dir)
    except FileNotFoundError:
        logger.info("no condo run found; screening residential only")
        return None
    condo_mart = root / "marts" / "condo_sale_features.parquet"
    if not condo_mart.exists():
        logger.info("condo mart missing; screening residential only")
        return None
    marts = (
        ("condo_sale_features", read_derived_manifest(condo_mart).built_at),
        ("sale_features", residential_mart_built),
    )
    _require_coherent(condo_run, marts, allow_stale=allow_stale)

    proximity_path = root / "marts" / "proximity.parquet"
    features = assemble_condo_assessment_features(
        pl.scan_parquet(paths["opa"]),
        pl.scan_parquet(paths["sales"]),
        valuation_date,
        pl.scan_parquet(paths["market_areas"]),
        pl.read_parquet(paths["price_index"]),
        pl.scan_parquet(proximity_path) if proximity_path.exists() else None,
    )
    # pin row order for reproducible interval draws (see the residential arm)
    features = features.sort("parcel_id")
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
        pred = pred * np.exp(-features["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy())
    condo_calibration = lightgbm_median_ratio(condo_run, model="condo_lightgbm")

    from philly_fair_measure.models.conformal import (
        calibration_from_run,
        conformal_offsets,
        xy_district,
    )

    cal = calibration_from_run(condo_run, data_dir)
    xy, district = xy_district(features)
    lo_off, hi_off = conformal_offsets(cal, xy, district, method="knn")
    # the conformal residuals are measured around the isotonic-calibrated
    # prediction, so that prediction anchors the interval and the flags
    median = pred
    pi_low, pi_high = pred * np.exp(lo_off), pred * np.exp(hi_off)
    interval_method = IntervalMethod.CONFORMAL

    frame = features.select(
        "parcel_id",
        pl.concat_str([pl.col("address"), pl.col("unit").fill_null("")], separator=" #").alias(
            "address"
        ),
        "char_category",
        pl.col("char_unit_area").alias("char_livable_area"),
        "char_year_built",
        "char_interior_condition",
        "loc_zip5",
        "loc_ward",
        "mkt_bldg_roll_n",
        "bldg_n_units",
        # the equity peer group excludes the subject's own building — a
        # 335-unit tower must not be its own "equal treatment" benchmark
        "building_id",
        "opa_market_value",
    ).with_columns(
        pl.Series("pred_lightgbm", pred),
        pl.Series("pred_lightgbm_calibrated", pred / condo_calibration),
        pl.Series("model_median", median),
        pl.Series("model_pi_low_90", pi_low),
        pl.Series("model_pi_high_90", pi_high),
        pl.lit(ModelFamily.CONDO).alias("model_family"),
        pl.lit(interval_method).alias("interval_method"),
        pl.lit(valuation_date).alias("valuation_date"),
    )
    return frame, [condo_run]
