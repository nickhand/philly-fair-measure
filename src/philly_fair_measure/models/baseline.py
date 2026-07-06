"""Baseline valuation models (Milestone 6 + plan v2): LightGBM plus a Ridge
benchmark, evaluated against sale prices and against OPA's own assessments.

Design decisions:

- **`asmt_*` features are excluded from model inputs.** The point of the
  baseline is an independent estimate to compare *against* OPA; a model that
  can see the assessment would trivially copy it and the comparison would be
  circular. They are used only as the incumbent benchmark on the test set.
- **Time-adjusted training (default, OPA practice):** the target is
  log(price) + time_adj_log — the sale expressed in reference-month dollars
  via the district price index — and time features are dropped. Predictions
  are moved back to the sale date with the same adjustment before evaluation,
  so metrics remain comparable with the v1 raw-time design
  (`time_adjusted=False`).
- **Out-of-time split** (CCAO practice): the most recent `test_fraction` of
  sales by date is the test set; the most recent slice of the remainder is the
  early-stopping validation set.
- Evaluation reports two conventions: `out_of_time` (estimate at sale date vs
  actual price — our headline) and `time_adjusted` (estimate vs time-adjusted
  price, the IAAO/Keene ratio-study convention, overall only). Segments cover
  category, price quintile, and parsed style (singles/twins/rows analog).
- Residential scope: SINGLE FAMILY + MULTI FAMILY.

Every run writes to data/models/run_id=<stamp>-baseline/: model, params
(including exact feature lists, so scoring is run-portable), categorical
encodings, predictions, feature importance, evaluation table, and a
provenance manifest.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import polars as pl

if TYPE_CHECKING:
    from sklearn.pipeline import Pipeline

from philly_fair_measure import __version__, config
from philly_fair_measure.ingest.manifests import (
    DerivedManifest,
    InputRef,
    read_derived_manifest,
    write_derived_manifest,
)
from philly_fair_measure.models.metrics import evaluate_estimates
from philly_fair_measure.vocab import Market

logger = logging.getLogger(__name__)

RESIDENTIAL_CATEGORIES: Final = ("SINGLE FAMILY", "MULTI FAMILY")

NUMERIC_FEATURES: Final = (
    "char_livable_area",
    "char_lot_area",
    "char_frontage",
    "char_depth",
    "char_beds",
    "char_baths",
    "char_rooms",
    "char_stories",
    "char_year_built",
    "char_garage_spaces",
    "char_fireplaces",
    "mkt_block_roll_mean_price",
    "mkt_block_roll_ppsf",
    "mkt_block_roll_n",
    "mkt_knn_log_ppsf",
    "mkt_knn_n",
    "mkt_knn_mean_dist_m",
    # new-construction comp surface: what then-new homes sold for nearby —
    # the pool a brand-new build actually belongs to (features/spatial.py)
    "char_new_build",
    "mkt_newbuild_knn_log_ppsf",
    "mkt_newbuild_knn_n",
    "mkt_newbuild_knn_mean_dist_m",
    "mkt_newbuild_premium",
    "mkt_area_level_log_ppsf",
    "mkt_parcel_n_prior_sales",
    "mkt_parcel_days_since_prev",
    "mkt_parcel_prev_price",
    "mkt_parcel_prev_log_price_ref",
    "evt_n_permits_5y_before",
    "evt_days_since_last_permit",
    # renovation-class permits (alterations/major/change-of-use): the public
    # trace of the latent renovated-vs-shell state driving within-block errors
    "evt_n_reno_permits_5y_before",
    "evt_days_since_last_reno_permit",
    "evt_n_violations_5y_before",
    "evt_n_open_violations_at_sale",
    # distress signals for the q1 tail (plan v2 follow-up)
    "evt_n_severe_violations_5y_before",
    "evt_n_open_severe_at_sale",
    "evt_n_demolitions_before",
    "evt_demo_days_since",
    "dist_tax_delinquent",
    "dist_tax_years_owed",
    "dist_tax_total_due",
    "dist_sheriff_sale",
    # L&I complaint/inspection/tenure family (the q1 follow-up round two:
    # resident-reported interior distress, vacancy, escalation, tenure)
    "evt_n_complaints_5y_before",
    "evt_n_int_maint_complaints_5y_before",
    "evt_n_ext_maint_complaints_5y_before",
    "evt_n_vacant_complaints_5y_before",
    "evt_n_unpermitted_work_complaints_5y_before",
    "evt_vacant_complaint_days_since",
    "evt_n_investigations_5y_before",
    "evt_n_precourt_5y_before",
    "evt_n_appeal_granted_before",
    "ten_rental_license_at_sale",
    "ten_owner_occupied_rental",
    "ten_rental_units",
    # mortgage forensics (RTT MORTGAGE docs; amounts unrecorded — presence,
    # timing, lender identity only). fin_cash_sale/fin_hard_money_sale are
    # transaction attributes and stay OUT of the model (asmt_-style analysis
    # columns).
    "fin_n_mortgages_5y_before",
    "fin_mtg_days_since",
    "fin_refi_5y_before",
    "fin_hard_money_5y_before",
    "loc_lon",
    "loc_lat",
    # parcel geometry (PWD polygons via the brt_id bridge; plan v2 Tier 2.1)
    "shp_parcel_area_m2",
    "shp_parcel_perimeter_m",
    "shp_parcel_num_vertices",
    "shp_parcel_edge_len_sd_m",
    "shp_parcel_interior_angle_sd_deg",
    "shp_parcel_centroid_dist_sd_m",
    "shp_parcel_mrr_area_ratio",
    "shp_parcel_mrr_side_ratio",
    "shp_parcel_num_brt",
    "shp_parcel_num_accounts",
    "shp_n_linked_parcels",
    "shp_linked_lot_area_m2",
    # quasi-static proximity (features/proximity.py; the last OPA-parity family)
    "prox_dist_rapid_transit_m",
    "prox_dist_regional_rail_m",
    "prox_dist_park_m",
    "prox_dist_expressway_m",
    "prox_dist_arterial_m",
    "prox_n_bus_stops_800m",
    "prox_dist_bike_network_m",
    "prox_parcel_density_400m",
    "prox_dist_vacant_land_m",
)
TIME_FEATURES: Final = ("time_sale_epoch_days", "time_quarter", "time_month")
CATEGORICAL_FEATURES: Final = (
    "char_category",
    "char_building_type",
    "char_style",
    "char_era",
    "char_exterior_condition",
    "char_interior_condition",
    "char_quality_grade_raw",
    "char_basement",
    "char_central_air",
    "char_heater",
    "char_construction",
    "char_view",
    "char_topography",
    "loc_zip5",
    "loc_ward",
    "loc_census_tract_raw",
    "loc_market_area",
    "loc_district",
    "loc_street_class",
)
STYLE_SEGMENTS: Final = ("row", "twin", "detached")

DEFAULT_LGB_PARAMS: Final = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 255,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l1": 0.1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "seed": 42,
}

RIDGE_NUMERIC_BASE: Final = (
    "char_livable_area",
    "char_lot_area",
    "char_beds",
    "char_baths",
    "char_year_built",
    "mkt_block_roll_mean_price",
    "mkt_knn_log_ppsf",
)
RIDGE_ONEHOT: Final = ("char_category", "loc_zip5")


def feature_lists(time_adjusted: bool) -> tuple[list[str], list[str]]:
    numeric = list(NUMERIC_FEATURES) + ([] if time_adjusted else list(TIME_FEATURES))
    return numeric, list(CATEGORICAL_FEATURES)


def _load_frame(mart_path: Path) -> pl.DataFrame:
    frame = (
        pl.read_parquet(mart_path)
        .filter(pl.col("char_category").is_in(RESIDENTIAL_CATEGORIES))
        .with_columns(
            (pl.col("sale_date") - pl.datetime(1997, 1, 1))
            .dt.total_days()
            .alias("time_sale_epoch_days")
        )
        .sort("sale_date", "sale_id")
    )
    if "time_adj_log" not in frame.columns:
        frame = frame.with_columns(pl.lit(0.0).alias("time_adj_log"))
    return frame


def _fit_category_mappings(df: pl.DataFrame, categorical: list[str]) -> dict[str, dict[str, int]]:
    mappings = {}
    for column in categorical:
        values = df[column].cast(pl.String).drop_nulls().unique().sort().to_list()
        mappings[column] = {value: code for code, value in enumerate(values)}
    return mappings


def _encode(
    df: pl.DataFrame,
    mappings: dict[str, dict[str, int]],
    numeric: list[str],
    categorical: list[str],
) -> np.ndarray:
    exprs = [pl.col(c).cast(pl.Float64) for c in numeric]
    exprs += [
        pl.col(c).cast(pl.String).replace_strict(mappings[c], default=None).cast(pl.Float64)
        for c in categorical
    ]
    return df.select(exprs).to_numpy()


def _train_ridge(
    train_df: pl.DataFrame, y_train: np.ndarray, ridge_numeric: list[str]
) -> tuple[Pipeline, Callable[[pl.DataFrame], np.ndarray]]:
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric_ix = list(range(len(ridge_numeric)))
    onehot_ix = list(range(len(ridge_numeric), len(ridge_numeric) + len(RIDGE_ONEHOT)))
    pipeline = Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        (
                            "num",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="median")),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                            numeric_ix,
                        ),
                        (
                            "cat",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                            onehot_ix,
                        ),
                    ]
                ),
            ),
            ("ridge", Ridge(alpha=1.0)),
        ]
    )

    def matrix(df: pl.DataFrame) -> np.ndarray:
        return df.select(
            *[pl.col(c).cast(pl.Float64) for c in ridge_numeric],
            *[pl.col(c).cast(pl.String).fill_null("__missing__") for c in RIDGE_ONEHOT],
        ).to_numpy()

    pipeline.fit(matrix(train_df), y_train)
    return pipeline, matrix


class Calibration(TypedDict):
    """Isotonic vertical-equity correction as monotone knot coordinates.

    A plain dict at runtime (serialized verbatim to vertical_calibration.json and
    reloaded via json.loads), so the shape is documented and key access is typed
    without any bespoke (de)serialization.
    """

    x: list[float]
    y: list[float]


def fit_vertical_calibration(pred_log: npt.ArrayLike, actual_log: npt.ArrayLike) -> Calibration:
    """Monotone correction of E[log price | predicted log price], fitted on the
    validation slice — the ML analog of assessors' vertical-equity adjustments.

    The gradient it removes: with under-informative features at the tails,
    predictions compress toward segment means, over-valuing cheap homes and
    under-valuing expensive ones (PRD > 1). Isotonic regression of the residual
    on the prediction is increasing by construction, so the calibrated
    prediction remains monotone in the raw one.
    """
    from sklearn.isotonic import IsotonicRegression

    pred = np.asarray(pred_log, dtype=np.float64)
    actual = np.asarray(actual_log, dtype=np.float64)
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(pred, actual - pred)
    return {
        "x": [float(v) for v in iso.X_thresholds_],
        "y": [float(v) for v in iso.y_thresholds_],
    }


def apply_vertical_calibration(
    pred_log: npt.ArrayLike, calibration: Calibration
) -> npt.NDArray[np.float64]:
    pred = np.asarray(pred_log, dtype=np.float64)
    correction = np.interp(pred, calibration["x"], calibration["y"])
    return np.asarray(pred + correction, dtype=np.float64)


def _segments(test_df: pl.DataFrame) -> list[tuple[str, str, pl.Series]]:
    """(segment_type, segment, row mask) triples for evaluation breakouts."""
    out = [("overall", "overall", pl.Series([True] * test_df.height))]
    for category in RESIDENTIAL_CATEGORIES:
        out.append(("category", category, test_df["char_category"] == category))
    if "char_style" in test_df.columns:
        for style in STYLE_SEGMENTS:
            out.append(("style", style, test_df["char_style"] == style))
    edges = np.quantile(test_df["sale_price"].to_numpy(), [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(test_df["sale_price"].to_numpy(), edges) + 1
    for q in range(1, 6):
        out.append(("price_quintile", f"q{q}", pl.Series(quintile == q)))
    return out


@dataclass(frozen=True)
class BaselineRunResult:
    run_dir: Path
    run_id: str
    overall: dict[str, dict]
    evaluation: pl.DataFrame


_MIN_CALIBRATION_ROWS: Final = 200  # below this, financed-only calibration is too thin


def train_baseline(
    data_dir: Path | None = None,
    *,
    test_fraction: float = 0.1,
    validation_fraction: float = 0.1,
    time_adjusted: bool = True,
    vertical_calibration: bool = True,
    calibrate_on_financed: bool = True,
    market: Market | str = Market.BLEND,
    lgb_params: dict | None = None,
    num_boost_round: int = 5000,
    early_stopping_rounds: int = 100,
) -> BaselineRunResult:
    """`market=Market.RETAIL` trains only on mortgage-financed sales (the
    typical-financing standard) — its predictions are retail value. The run is
    tagged kind "retail" (not "baseline") so it never displaces the blend model
    the screen scores by default."""
    market = Market(market)
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "sale_features.parquet"
    if not mart_path.exists():
        raise FileNotFoundError(f"{mart_path} missing; run `fair-measure build-features` first")

    df = _load_frame(mart_path)
    numeric, categorical = feature_lists(time_adjusted)
    features = numeric + categorical

    n_test = max(1, int(df.height * test_fraction))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train_df.height * validation_fraction))
    fit_df, val_df = train_df.head(train_df.height - n_val), train_df.tail(n_val)
    if market is Market.RETAIL:
        financed = pl.col("fin_cash_sale").fill_null(1.0) == 0.0
        fit_df, val_df = fit_df.filter(financed), val_df.filter(financed)
    logger.info(
        "residential sales: %s train / %s val / %s test (test from %s, time_adjusted=%s)",
        f"{fit_df.height:,}",
        f"{val_df.height:,}",
        f"{test_df.height:,}",
        test_df["sale_date"].min(),
        time_adjusted,
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

    params = {**DEFAULT_LGB_PARAMS, **(lgb_params or {})}
    train_set = lgb.Dataset(
        x["fit"], label=y["fit"], feature_name=features, categorical_feature=categorical
    )
    val_set = train_set.create_valid(x["val"], label=y["val"])
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
    )

    test_adj = test_df["time_adj_log"].to_numpy() if time_adjusted else np.zeros(test_df.height)
    pred_lgb_ref = booster.predict(x["test"], num_iteration=booster.best_iteration)
    calibration = None
    if vertical_calibration:
        val_pred_ref = booster.predict(x["val"], num_iteration=booster.best_iteration)
        # Center the isotonic on the market-value (typical-financing) standard by
        # fitting it on financed val only: predictions land at market value, not
        # the cash-blended sale level. Measured 2026-07-05 — financed median ratio
        # 0.95 -> 1.00 with COD/PRD/PRB unchanged. Falls back to all val where the
        # financed subset is thin or absent (e.g. synthetic marts).
        cal_mask = np.ones(val_df.height, dtype=bool)
        if calibrate_on_financed and "fin_cash_sale" in val_df.columns:
            fin_rows = (val_df["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()
            if int(fin_rows.sum()) >= _MIN_CALIBRATION_ROWS:
                cal_mask = fin_rows
        calibration = fit_vertical_calibration(val_pred_ref[cal_mask], y["val"][cal_mask])
        pred_lgb_ref = apply_vertical_calibration(pred_lgb_ref, calibration)
    pred_lgb = np.exp(pred_lgb_ref - test_adj)

    ridge_numeric = list(RIDGE_NUMERIC_BASE) + ([] if time_adjusted else ["time_sale_epoch_days"])
    ridge, ridge_matrix = _train_ridge(fit_df, y["fit"], ridge_numeric)
    pred_ridge_ref = ridge.predict(ridge_matrix(test_df))
    pred_ridge = np.exp(pred_ridge_ref - test_adj)

    sale_price = test_df["sale_price"].to_numpy()
    opa_value = test_df["asmt_market_value_sale_year"].to_numpy()
    estimates = {"lightgbm": pred_lgb, "ridge": pred_ridge, "opa_assessment": opa_value}

    rows = []
    for segment_type, segment, mask in _segments(test_df):
        m = mask.to_numpy()
        for model, estimate in estimates.items():
            rows.append(
                {
                    "model": model,
                    "convention": "out_of_time",
                    "segment_type": segment_type,
                    "segment": segment,
                    **evaluate_estimates(estimate[m], sale_price[m]).as_row(),
                }
            )
    # IAAO/Keene convention: estimates vs time-adjusted sale prices, overall only
    price_tasp = sale_price * np.exp(test_adj)
    tasp_estimates = {
        "lightgbm": np.exp(pred_lgb_ref),
        "ridge": np.exp(pred_ridge_ref),
        "opa_assessment": opa_value,
    }
    for model, estimate in tasp_estimates.items():
        rows.append(
            {
                "model": model,
                "convention": "time_adjusted",
                "segment_type": "overall",
                "segment": "overall",
                **evaluate_estimates(estimate, price_tasp).as_row(),
            }
        )
    evaluation = pl.DataFrame(rows)
    overall = {
        row["model"]: row
        for row in evaluation.filter(
            (pl.col("segment_type") == "overall") & (pl.col("convention") == "out_of_time")
        ).to_dicts()
    }

    run_kind = "baseline" if market is Market.BLEND else "retail"
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + run_kind
    run_dir = root / "models" / f"run_id={run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    booster.save_model(run_dir / "model_lightgbm.txt")
    (run_dir / "params.json").write_text(
        json.dumps(
            {
                "lgb_params": params,
                "best_iteration": booster.best_iteration,
                "num_boost_round": num_boost_round,
                "test_fraction": test_fraction,
                "validation_fraction": validation_fraction,
                "time_adjusted": time_adjusted,
                "vertical_calibration": vertical_calibration,
                "calibrate_on_financed": calibrate_on_financed,
                "market": market,
                "features": features,
                "numeric_features": numeric,
                "categorical_features": categorical,
                "residential_categories": list(RESIDENTIAL_CATEGORIES),
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
        pl.Series("pred_lightgbm", pred_lgb),
        pl.Series("pred_ridge", pred_ridge),
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
        notes="row_count is the test-set size; see params.json for split details",
    )
    write_derived_manifest(manifest, run_dir / "run.parquet")
    logger.info("baseline run %s -> %s", run_id, run_dir)
    return BaselineRunResult(run_dir=run_dir, run_id=run_id, overall=overall, evaluation=evaluation)
