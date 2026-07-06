"""ACS-features sensitivity: what does the people-data ban cost in accuracy?

OPA is legally barred from income/demographic/crime features
(docs/research-notes.md), and this project keeps demographics
diagnostics-only by design — demographic variables are never valuation
features, only after-the-fact checks (docs/equity-diagnostics.md showed the
demographic-free model already collapses OPA's racial ratio gap).
This module measures the constraint's price: one toggled retrain of the
residential LightGBM with tract-level ACS aggregates joined as features,
against the identical out-of-time split, params, and seed.

It is strictly a DIAGNOSTIC: the ACS-augmented model is never persisted as a
run and never scores the screen. The interesting outputs are (1) the accuracy
delta, and (2) whether ratio levels by tract majority-race group move — i.e.
whether the features the law forbids would have bought accuracy, fairness,
neither, or both.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure import catalog, config

logger = logging.getLogger(__name__)

ACS_DATASET = "acs_tract_demographics"
ACS_FEATURES = [
    "acs_pct_white",
    "acs_pct_black",
    "acs_pct_hispanic",
    "acs_pct_asian",
    "acs_median_income",
    "acs_poverty_rate",
]


def _acs_frame(data_dir: Path | None) -> pl.DataFrame:
    ref = catalog.latest_snapshots(data_dir).get(ACS_DATASET)
    if ref is None:
        raise FileNotFoundError(
            f"no {ACS_DATASET} snapshot; run `fair-measure snapshot arcgis "
            "Philadelphia_Census_Tracts_ACS_2022_Select_Demographics "
            f"--dataset {ACS_DATASET}` first"
        )
    pop = pl.col("totl_pp").cast(pl.Float64, strict=False)

    def share(column: str) -> pl.Expr:
        return (
            pl.when(pop > 0)
            .then(pl.col(column).cast(pl.Float64, strict=False) / pop)
            .otherwise(None)
        )

    return pl.read_parquet(ref.data_path).select(
        pl.col("GEOID").cast(pl.String).alias("acs_geoid"),
        share("white").alias("acs_pct_white"),
        share("black").alias("acs_pct_black"),
        share("hispanc").alias("acs_pct_hispanic"),
        share("asian").alias("acs_pct_asian"),
        pl.col("mdn_ncm").cast(pl.Float64, strict=False).alias("acs_median_income"),
        pl.col("pvrty_r").cast(pl.Float64, strict=False).alias("acs_poverty_rate"),
        pl.col("mjrty_r").cast(pl.String).alias("acs_majority_race"),
        "geometry_geojson",
    )


def join_tracts(df: pl.DataFrame, acs: pl.DataFrame) -> pl.DataFrame:
    """Point-in-tract join of sale rows (loc_lon/loc_lat) to the ACS layer."""
    from shapely import STRtree, from_geojson, points

    polys = from_geojson(acs["geometry_geojson"].to_numpy(), on_invalid="ignore")
    valid_poly = np.array([p is not None and not p.is_empty for p in polys])
    tree = STRtree(polys[valid_poly])
    poly_row = np.flatnonzero(valid_poly)

    lon = df["loc_lon"].cast(pl.Float64).to_numpy()
    lat = df["loc_lat"].cast(pl.Float64).to_numpy()
    located = np.isfinite(lon) & np.isfinite(lat)
    pts = points(lon[located], lat[located])
    hit_pt, hit_poly = tree.query(pts, predicate="within")

    tract_ix = np.full(df.height, -1, dtype=np.int64)
    located_rows = np.flatnonzero(located)
    tract_ix[located_rows[hit_pt]] = poly_row[hit_poly]
    matched = tract_ix >= 0
    logger.info(
        "tract join: %s of %s rows matched (%.1f%%)",
        f"{int(matched.sum()):,}",
        f"{df.height:,}",
        100 * matched.mean(),
    )
    acs_cols = acs.drop("geometry_geojson")
    joined = acs_cols[np.where(matched, tract_ix, 0)].with_columns(pl.Series("_matched", matched))
    joined = joined.select(
        *[
            pl.when(pl.col("_matched")).then(pl.col(c)).otherwise(None).alias(c)
            for c in acs_cols.columns
        ]
    )
    return pl.concat([df, joined], how="horizontal")


def run_acs_sensitivity(
    data_dir: Path | None = None,
    *,
    test_fraction: float = 0.1,
    validation_fraction: float = 0.1,
    num_boost_round: int = 5000,
    early_stopping_rounds: int = 100,
) -> pl.DataFrame:
    """Train baseline-features vs baseline+ACS on the identical split; return
    the comparison table (also persisted under diagnostics/)."""
    import lightgbm as lgb

    from philly_fair_measure.ingest.derived import write_derived_table
    from philly_fair_measure.models.baseline import (
        DEFAULT_LGB_PARAMS,
        _encode,
        _fit_category_mappings,
        _load_frame,
        apply_vertical_calibration,
        feature_lists,
        fit_vertical_calibration,
    )
    from philly_fair_measure.models.metrics import evaluate_estimates

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    df = join_tracts(df, _acs_frame(data_dir))

    numeric, categorical = feature_lists(time_adjusted=True)
    variants = {"baseline": numeric, "with_acs": numeric + ACS_FEATURES}

    n_test = max(1, int(df.height * test_fraction))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train_df.height * validation_fraction))
    fit_df, val_df = train_df.head(train_df.height - n_val), train_df.tail(n_val)
    logger.info(
        "acs sensitivity: %s fit / %s val / %s test",
        f"{fit_df.height:,}",
        f"{val_df.height:,}",
        f"{test_df.height:,}",
    )

    def target(frame: pl.DataFrame) -> np.ndarray:
        y = np.log(frame["sale_price"].to_numpy()) + frame["time_adj_log"].to_numpy()
        return np.asarray(y, dtype=np.float64)

    y_fit, y_val = target(fit_df), target(val_df)
    test_adj = test_df["time_adj_log"].to_numpy()
    sale_price = test_df["sale_price"].to_numpy()

    estimates: dict[str, np.ndarray] = {}
    for name, features_numeric in variants.items():
        mappings = _fit_category_mappings(fit_df, categorical)
        features = features_numeric + categorical
        x_fit = _encode(fit_df, mappings, features_numeric, categorical)
        x_val = _encode(val_df, mappings, features_numeric, categorical)
        x_test = _encode(test_df, mappings, features_numeric, categorical)
        train_set = lgb.Dataset(
            x_fit, label=y_fit, feature_name=features, categorical_feature=categorical
        )
        booster = lgb.train(
            DEFAULT_LGB_PARAMS,
            train_set,
            num_boost_round=num_boost_round,
            valid_sets=[train_set.create_valid(x_val, label=y_val)],
            callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
        )
        pred_ref = booster.predict(x_test, num_iteration=booster.best_iteration)
        calibration = fit_vertical_calibration(
            booster.predict(x_val, num_iteration=booster.best_iteration), y_val
        )
        pred_ref = apply_vertical_calibration(pred_ref, calibration)
        estimates[name] = np.exp(pred_ref - test_adj)
        if name == "with_acs":
            gain = booster.feature_importance(importance_type="gain")
            acs_share = gain[[features.index(f) for f in ACS_FEATURES]].sum() / gain.sum()
            logger.info("ACS features carry %.2f%% of total gain", 100 * acs_share)
    estimates["opa_assessment"] = test_df["asmt_market_value_sale_year"].to_numpy()

    segments: list[tuple[str, str, np.ndarray]] = [
        ("overall", "overall", np.ones(test_df.height, dtype=bool))
    ]
    edges = np.quantile(sale_price, [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(sale_price, edges) + 1
    for q in range(1, 6):
        segments.append(("price_quintile", f"q{q}", quintile == q))
    majority = test_df["acs_majority_race"].fill_null("unmatched").to_numpy()
    for group in np.unique(majority):
        mask = majority == group
        if mask.sum() >= 200:
            segments.append(("tract_majority_race", str(group), mask))

    rows = []
    for model, estimate in estimates.items():
        for segment_type, segment, mask in segments:
            rows.append(
                {
                    "model": model,
                    "segment_type": segment_type,
                    "segment": segment,
                    **evaluate_estimates(estimate[mask], sale_price[mask]).as_row(),
                }
            )
    table = pl.DataFrame(rows)
    write_derived_table(
        table,
        root,
        "diagnostics",
        "acs_sensitivity",
        [],
        notes="diagnostic only: ACS-augmented model is never a production run",
    )
    return table
