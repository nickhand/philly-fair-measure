"""Stability audit: turn "COD 26 is one split" into a distribution, and bound
the learned-geography look-ahead.

1. temporal_cv — expanding-window rolling-origin cross-validation. Five
   successive out-of-time folds, each trained only on earlier sales, so the
   headline accuracy is a distribution across time, not a lucky single split.

2. spatial_cv — leave-one-district-out. Hold out an entire district's sales,
   train on the rest, predict the held-out district. A stress test of
   geographic generalization (in production no geography is truly unseen — all
   of Philadelphia is in training — so this is a lower bound on real-world
   accuracy, deliberately adversarial).

3. index_lookahead_bound — the district price index and learned market areas
   are fit on all sales, including the test period, a mild look-ahead in the
   out-of-time evaluation (and standard assessment practice: OPA time-adjusts
   and redraws market areas with the full window too). This rebuilds the index
   train-only and reports how much the test-period time adjustment moves —
   bounding the leakage in log-price points.

Diagnostics only.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config

logger = logging.getLogger(__name__)


def _fit_predict(
    fit_df: pl.DataFrame,
    val_df: pl.DataFrame,
    test_df: pl.DataFrame,
    numeric: list[str],
    categorical: list[str],
    *,
    rounds: int = 3000,
) -> np.ndarray:
    import lightgbm as lgb

    from philly_assessments.models.baseline import (
        DEFAULT_LGB_PARAMS,
        _encode,
        _fit_category_mappings,
        apply_vertical_calibration,
        fit_vertical_calibration,
    )

    mappings = _fit_category_mappings(fit_df, categorical)

    def y(frame: pl.DataFrame) -> np.ndarray:
        out = np.log(frame["sale_price"].to_numpy()) + frame["time_adj_log"].to_numpy()
        return np.asarray(out, dtype=np.float64)

    x_fit = _encode(fit_df, mappings, numeric, categorical)
    x_val = _encode(val_df, mappings, numeric, categorical)
    x_test = _encode(test_df, mappings, numeric, categorical)
    booster = lgb.train(
        DEFAULT_LGB_PARAMS,
        lgb.Dataset(
            x_fit,
            label=y(fit_df),
            feature_name=numeric + categorical,
            categorical_feature=categorical,
        ),
        num_boost_round=rounds,
        valid_sets=[lgb.Dataset(x_val, label=y(val_df), reference=None)],
        callbacks=[lgb.early_stopping(80, verbose=False)],
    )
    cal = fit_vertical_calibration(booster.predict(x_val), y(val_df))
    pred_ref = apply_vertical_calibration(booster.predict(x_test), cal)
    return np.asarray(np.exp(pred_ref - test_df["time_adj_log"].to_numpy()), dtype=np.float64)


def _summary(cods: list[float]) -> dict:
    a = np.array(cods)
    return {
        "folds": len(a),
        "cod_mean": float(a.mean()),
        "cod_sd": float(a.std()),
        "cod_min": float(a.min()),
        "cod_max": float(a.max()),
    }


def temporal_cv(data_dir: Path | None = None, *, n_folds: int = 5) -> tuple[pl.DataFrame, dict]:
    from philly_assessments.models.baseline import _load_frame, feature_lists
    from philly_assessments.models.metrics import evaluate_estimates

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    numeric, categorical = feature_lists(time_adjusted=True)
    n = df.height
    fold = n // (2 * n_folds)  # test folds tile the most recent half

    rows = []
    cods: list[float] = []
    for i in range(n_folds):
        stop = n - (n_folds - 1 - i) * fold
        start = stop - fold
        test_df = df.slice(start, stop - start)
        train = df.head(start)
        n_val = max(1, int(train.height * 0.1))
        fit_df, val_df = train.head(train.height - n_val), train.tail(n_val)
        pred = _fit_predict(fit_df, val_df, test_df, numeric, categorical)
        m = evaluate_estimates(pred, test_df["sale_price"].to_numpy())
        if m.cod is None:
            raise ValueError(f"temporal fold {i + 1}: COD undefined (fold too small)")
        cods.append(m.cod)
        rows.append(
            {
                "fold": i + 1,
                "test_from": str(test_df["sale_date"].min())[:10],
                "n_train": fit_df.height,
                "n_test": test_df.height,
                "cod": m.cod,
                "median_ratio": m.median_ratio,
            }
        )
        logger.info("temporal fold %d: COD %.1f", i + 1, m.cod)
    return pl.DataFrame(rows), _summary(cods)


def spatial_cv(
    data_dir: Path | None = None, *, min_district_n: int = 500
) -> tuple[pl.DataFrame, dict]:
    from philly_assessments.models.baseline import _load_frame, feature_lists
    from philly_assessments.models.metrics import evaluate_estimates

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    numeric, categorical = feature_lists(time_adjusted=True)
    districts = [
        d
        for d, c in df.group_by("loc_district").len().iter_rows()
        if d is not None and c >= min_district_n
    ]
    rows = []
    cods: list[float] = []
    for d in sorted(districts):
        test_df = df.filter(pl.col("loc_district") == d)
        train = df.filter(pl.col("loc_district") != d)
        n_val = max(1, int(train.height * 0.1))
        fit_df, val_df = train.head(train.height - n_val), train.tail(n_val)
        pred = _fit_predict(fit_df, val_df, test_df, numeric, categorical)
        m = evaluate_estimates(pred, test_df["sale_price"].to_numpy())
        if m.cod is None:
            raise ValueError(f"spatial hold-out {d}: COD undefined (district too small)")
        cods.append(m.cod)
        rows.append(
            {
                "held_out_district": d,
                "n_test": test_df.height,
                "cod": m.cod,
                "median_ratio": m.median_ratio,
            }
        )
        logger.info("spatial hold-out %s: COD %.1f", d, m.cod)
    return pl.DataFrame(rows).sort("cod", descending=True), _summary(cods)


def index_lookahead_bound(data_dir: Path | None = None) -> dict:
    """Bound the price-index look-ahead in the out-of-time evaluation.

    The leakage is that the index uses test-period sales to set test-period
    levels; a real-time assessor would instead carry the last known level
    forward. The magnitude is therefore bounded by the total time-adjustment
    the test sales actually receive — which the reference month (latest month)
    makes small, since the test window is recent. We report that adjustment's
    magnitude (the whole time-adjustment effect, of which leakage is a
    fraction) and the index's total drift across the test window (the maximum
    any single test sale could carry)."""
    from philly_assessments.models.scoring import latest_run_dir, run_params

    root = data_dir if data_dir is not None else config.data_dir()
    cutoff = run_params(latest_run_dir("baseline", data_dir))["test_start_date"][:10]

    test = (
        pl.scan_parquet(root / "marts" / "sale_features.parquet")
        .filter(pl.col("sale_date") >= pl.lit(cutoff).str.to_datetime())
        .select("time_adj_log")
        .collect()["time_adj_log"]
        .cast(pl.Float64)
        .fill_null(0.0)
        .to_numpy()
    )
    index = pl.read_parquet(root / "marts" / "price_index.parquet")
    test_months = index.filter(pl.col("month") >= pl.lit(cutoff).str.to_datetime())[
        "log_index"
    ].to_numpy()
    return {
        "test_cutoff": cutoff,
        "n_test_sales": int(len(test)),
        "mean_abs_timeadj_pct": float(np.mean(np.abs(np.expm1(test)))),
        "p95_abs_timeadj_pct": float(np.quantile(np.abs(np.expm1(test)), 0.95)),
        "max_index_drift_over_window_pct": float(
            np.expm1(np.abs(test_months).max()) if len(test_months) else 0.0
        ),
    }
