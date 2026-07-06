"""Condominium valuation model (separate from residential, per CCAO practice).

Same training discipline as the residential baseline — out-of-time split,
time-adjusted target via the district price index, isotonic vertical
calibration, OPA as the incumbent benchmark — with the condo feature set:
unit characteristics, unit-area share (the public-data stand-in for declared
percent ownership), and the building-level leave-one-out rolling means that
CCAO found to be the workhorse. `building_id` itself is NOT a feature
(~9k mostly-singleton levels would overfit); the rolling mean carries the
building signal instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from philly_fair_measure import __version__, config
from philly_fair_measure.ingest.manifests import (
    DerivedManifest,
    InputRef,
    read_derived_manifest,
    write_derived_manifest,
)
from philly_fair_measure.models.baseline import (
    _encode,
    _fit_category_mappings,
    apply_vertical_calibration,
    fit_vertical_calibration,
)
from philly_fair_measure.models.metrics import evaluate_estimates

logger = logging.getLogger(__name__)

CONDO_NUMERIC = [
    "char_unit_area",
    "char_beds",
    "char_baths",
    "char_year_built",
    "char_floor",
    "unit_area_share",
    "bldg_n_units",
    "mkt_bldg_roll_mean_price",
    "mkt_bldg_roll_ppsf",
    "mkt_bldg_roll_n",
    "mkt_knn_log_ppsf",
    "mkt_knn_n",
    "mkt_knn_mean_dist_m",
    # repeat-sales carry-forward, as in the residential model: a unit's own
    # prior sale beats building averages that mix very different unit tiers
    "mkt_parcel_n_prior_sales",
    "mkt_parcel_days_since_prev",
    "mkt_parcel_prev_price",
    "mkt_parcel_prev_log_price_ref",
    "mkt_area_level_log_ppsf",
    "prox_dist_rapid_transit_m",
    "prox_dist_regional_rail_m",
    "prox_dist_park_m",
    "loc_lon",
    "loc_lat",
]
CONDO_TIME = ["time_quarter", "time_month"]
CONDO_CATEGORICAL = [
    "char_exterior_condition",
    "char_interior_condition",
    "char_quality_grade_raw",
    "char_era",
    "loc_zip5",
    "loc_market_area",
    "loc_district",
]

CONDO_LGB_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.9,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "seed": 42,
}

_SIZE_BANDS = [("bldg_1_5_units", 1, 5), ("bldg_6_49_units", 6, 49), ("bldg_50plus", 50, 10**9)]


@dataclass(frozen=True)
class CondoRunResult:
    run_dir: Path
    run_id: str
    overall: dict[str, dict]
    evaluation: pl.DataFrame


def train_condo(
    data_dir: Path | None = None,
    *,
    test_fraction: float = 0.15,
    validation_fraction: float = 0.15,
    time_adjusted: bool = True,
    vertical_calibration: bool = True,
    lgb_params: dict | None = None,
    num_boost_round: int = 3000,
    early_stopping_rounds: int = 100,
) -> CondoRunResult:
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "condo_sale_features.parquet"
    if not mart_path.exists():
        raise FileNotFoundError(
            f"{mart_path} missing; run `fair-measure build-condo-features` first"
        )

    df = pl.read_parquet(mart_path).sort("sale_date", "sale_id")
    if "time_adj_log" not in df.columns:
        df = df.with_columns(pl.lit(0.0).alias("time_adj_log"))
    numeric = list(CONDO_NUMERIC) + ([] if time_adjusted else list(CONDO_TIME))
    categorical = list(CONDO_CATEGORICAL)
    features = numeric + categorical

    n_test = max(1, int(df.height * test_fraction))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train_df.height * validation_fraction))
    fit_df, val_df = train_df.head(train_df.height - n_val), train_df.tail(n_val)
    logger.info(
        "condo sales: %s train / %s val / %s test (test from %s)",
        f"{fit_df.height:,}",
        f"{val_df.height:,}",
        f"{test_df.height:,}",
        test_df["sale_date"].min(),
    )

    mappings = _fit_category_mappings(fit_df, categorical)

    def target(frame: pl.DataFrame) -> np.ndarray:
        y = np.log(frame["sale_price"].to_numpy())
        if time_adjusted:
            y = y + frame["time_adj_log"].to_numpy()
        return np.asarray(y, dtype=np.float64)

    y = {
        name: target(frame) for name, frame in (("fit", fit_df), ("val", val_df), ("test", test_df))
    }
    x = {
        name: _encode(frame, mappings, numeric, categorical)
        for name, frame in (("fit", fit_df), ("val", val_df), ("test", test_df))
    }

    params = {**CONDO_LGB_PARAMS, **(lgb_params or {})}
    train_set = lgb.Dataset(
        x["fit"], label=y["fit"], feature_name=features, categorical_feature=categorical
    )
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[train_set.create_valid(x["val"], label=y["val"])],
        callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
    )

    test_adj = test_df["time_adj_log"].to_numpy() if time_adjusted else np.zeros(test_df.height)
    pred_ref = booster.predict(x["test"], num_iteration=booster.best_iteration)
    calibration = None
    if vertical_calibration:
        val_pred = booster.predict(x["val"], num_iteration=booster.best_iteration)
        calibration = fit_vertical_calibration(val_pred, y["val"])
        pred_ref = apply_vertical_calibration(pred_ref, calibration)
    pred = np.exp(pred_ref - test_adj)

    sale_price = test_df["sale_price"].to_numpy()
    opa_value = (
        test_df["asmt_market_value_sale_year"].to_numpy()
        if ("asmt_market_value_sale_year" in test_df.columns)
        else np.full(test_df.height, np.nan)
    )
    estimates = {"condo_lightgbm": pred, "opa_assessment": opa_value}

    segments: list[tuple[str, str, pl.Series]] = [
        ("overall", "overall", pl.Series([True] * test_df.height))
    ]
    for name, lo, hi in _SIZE_BANDS:
        segments.append(
            ("building_size", name, test_df["bldg_n_units"].is_between(lo, hi).fill_null(False))
        )
    edges = np.quantile(sale_price, [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(sale_price, edges) + 1
    for q in range(1, 6):
        segments.append(("price_quintile", f"q{q}", pl.Series(quintile == q)))

    rows = []
    for segment_type, segment, mask in segments:
        m = mask.to_numpy()
        for model, estimate in estimates.items():
            rows.append(
                {
                    "model": model,
                    "segment_type": segment_type,
                    "segment": segment,
                    **evaluate_estimates(estimate[m], sale_price[m]).as_row(),
                }
            )
    evaluation = pl.DataFrame(rows)
    overall = {
        row["model"]: row
        for row in evaluation.filter(pl.col("segment_type") == "overall").to_dicts()
    }

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-condo"
    run_dir = root / "models" / f"run_id={run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    booster.save_model(run_dir / "model_lightgbm.txt")
    (run_dir / "params.json").write_text(
        json.dumps(
            {
                "lgb_params": params,
                "best_iteration": booster.best_iteration,
                "test_fraction": test_fraction,
                "validation_fraction": validation_fraction,
                "time_adjusted": time_adjusted,
                "vertical_calibration": vertical_calibration,
                "features": features,
                "numeric_features": numeric,
                "categorical_features": categorical,
                "test_start_date": str(test_df["sale_date"].min()),
            },
            indent=2,
        )
        + "\n"
    )
    (run_dir / "categorical_mappings.json").write_text(json.dumps(mappings, indent=2) + "\n")
    if calibration is not None:
        (run_dir / "vertical_calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    evaluation.write_parquet(run_dir / "evaluation.parquet")
    pl.DataFrame(
        {
            "feature": features,
            "gain": booster.feature_importance(importance_type="gain"),
            "splits": booster.feature_importance(importance_type="split"),
        }
    ).sort("gain", descending=True).write_parquet(run_dir / "feature_importance.parquet")
    test_df.select("sale_id", "parcel_id", "sale_date", "sale_price").with_columns(
        pl.Series("pred_condo", pred),
        pl.Series("opa_assessment", opa_value),
    ).write_parquet(run_dir / "predictions.parquet")

    mart_manifest = read_derived_manifest(mart_path)
    manifest = DerivedManifest(
        layer="models",
        table=run_id,
        built_at=datetime.now(UTC),
        row_count=test_df.height,
        inputs=[
            InputRef(
                dataset=f"{mart_manifest.layer}/{mart_manifest.table}",
                fetched_at=mart_manifest.built_at.isoformat(),
            )
        ],
        package_version=__version__,
        notes="row_count is the test-set size",
    )
    write_derived_manifest(manifest, run_dir / "run.parquet")
    logger.info("condo run %s -> %s", run_id, run_dir)
    return CondoRunResult(run_dir=run_dir, run_id=run_id, overall=overall, evaluation=evaluation)
