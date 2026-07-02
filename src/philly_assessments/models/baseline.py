"""Baseline valuation models (Milestone 6): LightGBM plus a Ridge benchmark,
evaluated against sale prices and against OPA's own assessments.

Design decisions:

- **`asmt_*` features are excluded from model inputs.** The point of the
  baseline is an independent estimate to compare *against* OPA; a model that
  can see the assessment would trivially copy it and the comparison would be
  circular. They are used only as the incumbent benchmark on the test set.
- **Out-of-time split** (CCAO practice): the most recent `test_fraction` of
  sales by date is the test set; the most recent slice of the remainder is the
  early-stopping validation set.
- The OPA comparison slightly favors the model on market timing: the model
  sees sale-date features, while an assessment for year Y was certified before
  Y began. Interpret the gap accordingly — it is still the practically relevant
  benchmark ("which number is closer to what the property actually sold for").
- Residential scope: SINGLE FAMILY + MULTI FAMILY (Philly has no separate
  condominium category in `category_code_description`).

Every run writes to data/models/run_id=<stamp>-baseline/: model, params,
categorical encodings, predictions, feature importance, evaluation table, and
a provenance manifest — the CCAO run_id discipline.
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

from philly_assessments import __version__, config
from philly_assessments.ingest.manifests import (
    DerivedManifest,
    InputRef,
    read_derived_manifest,
    write_derived_manifest,
)
from philly_assessments.models.metrics import evaluate_estimates

logger = logging.getLogger(__name__)

RESIDENTIAL_CATEGORIES = ("SINGLE FAMILY", "MULTI FAMILY")

NUMERIC_FEATURES = [
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
    "mkt_block_roll_n",
    "mkt_parcel_n_prior_sales",
    "mkt_parcel_days_since_prev",
    "mkt_parcel_prev_price",
    "evt_n_permits_5y_before",
    "evt_days_since_last_permit",
    "evt_n_violations_5y_before",
    "evt_n_open_violations_at_sale",
    "loc_lon",
    "loc_lat",
    "time_sale_epoch_days",
    "time_quarter",
    "time_month",
]
CATEGORICAL_FEATURES = [
    "char_category",
    "char_building_type",
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
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

DEFAULT_LGB_PARAMS = {
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

# Ridge benchmark: a deliberately simple hedonic spec
RIDGE_NUMERIC = [
    "char_livable_area",
    "char_lot_area",
    "char_beds",
    "char_baths",
    "char_year_built",
    "mkt_block_roll_mean_price",
    "time_sale_epoch_days",
]
RIDGE_ONEHOT = ["char_category", "loc_zip5"]


def _load_frame(mart_path: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(mart_path)
        .filter(pl.col("char_category").is_in(RESIDENTIAL_CATEGORIES))
        .with_columns(
            (pl.col("sale_date") - pl.datetime(1997, 1, 1))
            .dt.total_days()
            .alias("time_sale_epoch_days")
        )
        .sort("sale_date", "sale_id")
    )


def _fit_category_mappings(df: pl.DataFrame) -> dict[str, dict[str, int]]:
    mappings = {}
    for column in CATEGORICAL_FEATURES:
        values = df[column].cast(pl.String).drop_nulls().unique().sort().to_list()
        mappings[column] = {value: code for code, value in enumerate(values)}
    return mappings


def _encode(df: pl.DataFrame, mappings: dict[str, dict[str, int]]) -> np.ndarray:
    exprs = [pl.col(c).cast(pl.Float64) for c in NUMERIC_FEATURES]
    exprs += [
        pl.col(c).cast(pl.String).replace_strict(mappings[c], default=None).cast(pl.Float64)
        for c in CATEGORICAL_FEATURES
    ]
    return df.select(exprs).to_numpy()


def _train_ridge(train_df: pl.DataFrame, y_train: np.ndarray):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric_ix = list(range(len(RIDGE_NUMERIC)))
    onehot_ix = list(range(len(RIDGE_NUMERIC), len(RIDGE_NUMERIC) + len(RIDGE_ONEHOT)))
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
            *[pl.col(c).cast(pl.Float64) for c in RIDGE_NUMERIC],
            *[pl.col(c).cast(pl.String).fill_null("__missing__") for c in RIDGE_ONEHOT],
        ).to_numpy()

    pipeline.fit(matrix(train_df), y_train)
    return pipeline, matrix


def _segments(test_df: pl.DataFrame) -> list[tuple[str, str, pl.Series]]:
    """(segment_type, segment, row mask) triples for evaluation breakouts."""
    out = [("overall", "overall", pl.Series([True] * test_df.height))]
    for category in RESIDENTIAL_CATEGORIES:
        out.append(("category", category, test_df["char_category"] == category))
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


def train_baseline(
    data_dir: Path | None = None,
    *,
    test_fraction: float = 0.1,
    validation_fraction: float = 0.1,
    lgb_params: dict | None = None,
    num_boost_round: int = 5000,
    early_stopping_rounds: int = 100,
) -> BaselineRunResult:
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "sale_features.parquet"
    if not mart_path.exists():
        raise FileNotFoundError(f"{mart_path} missing; run `philly build-features` first")

    df = _load_frame(mart_path)
    n_test = max(1, int(df.height * test_fraction))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train_df.height * validation_fraction))
    fit_df, val_df = train_df.head(train_df.height - n_val), train_df.tail(n_val)
    logger.info(
        "residential sales: %s train / %s val / %s test (test from %s)",
        f"{fit_df.height:,}",
        f"{val_df.height:,}",
        f"{test_df.height:,}",
        test_df["sale_date"].min(),
    )

    mappings = _fit_category_mappings(fit_df)
    y = {name: np.log(frame["sale_price"].to_numpy()) for name, frame in
         (("fit", fit_df), ("val", val_df), ("test", test_df))}
    x = {name: _encode(frame, mappings) for name, frame in
         (("fit", fit_df), ("val", val_df), ("test", test_df))}

    params = {**DEFAULT_LGB_PARAMS, **(lgb_params or {})}
    train_set = lgb.Dataset(
        x["fit"], label=y["fit"], feature_name=FEATURES, categorical_feature=CATEGORICAL_FEATURES
    )
    val_set = train_set.create_valid(x["val"], label=y["val"])
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
    )
    pred_lgb = np.exp(booster.predict(x["test"], num_iteration=booster.best_iteration))

    ridge, ridge_matrix = _train_ridge(fit_df, y["fit"])
    pred_ridge = np.exp(ridge.predict(ridge_matrix(test_df)))

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
                    "segment_type": segment_type,
                    "segment": segment,
                    **evaluate_estimates(estimate[m], sale_price[m]),
                }
            )
    evaluation = pl.DataFrame(rows)
    overall = {
        row["model"]: row
        for row in evaluation.filter(pl.col("segment_type") == "overall").to_dicts()
    }

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-baseline"
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
                "features": FEATURES,
                "categorical_features": CATEGORICAL_FEATURES,
                "residential_categories": list(RESIDENTIAL_CATEGORIES),
                "test_start_date": str(test_df["sale_date"].min()),
            },
            indent=2,
        )
        + "\n"
    )
    (run_dir / "categorical_mappings.json").write_text(json.dumps(mappings, indent=2) + "\n")
    evaluation.write_parquet(run_dir / "evaluation.parquet")
    pl.DataFrame(
        {
            "feature": FEATURES,
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
    return BaselineRunResult(
        run_dir=run_dir, run_id=run_id, overall=overall, evaluation=evaluation
    )
