import math
from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef
from philly_fair_measure.models.baseline import feature_lists, train_baseline
from philly_fair_measure.models.metrics import fit_metrics, ratio_metrics


def test_vertical_calibration_flattens_compression_gradient():
    from philly_fair_measure.models.baseline import (
        apply_vertical_calibration,
        fit_vertical_calibration,
    )

    rng = np.random.default_rng(0)
    actual = rng.uniform(10.0, 14.0, 4000)  # log prices
    # a model that compresses toward the mean (the PRD mechanism)
    pred = 12.0 + 0.7 * (actual - 12.0) + rng.normal(0, 0.05, 4000)
    calibration = fit_vertical_calibration(pred, actual)
    adjusted = apply_vertical_calibration(pred, calibration)

    low, high = actual < 11.0, actual > 13.0
    assert abs((adjusted - actual)[low].mean()) < 0.3 * abs((pred - actual)[low].mean())
    assert abs((adjusted - actual)[high].mean()) < 0.3 * abs((pred - actual)[high].mean())
    # monotone in the raw prediction
    order = np.argsort(pred)
    assert (np.diff(adjusted[order]) >= -1e-9).all()


def test_fit_metrics_known_values():
    out = fit_metrics([110_000.0, 90_000.0], [100_000.0, 100_000.0])
    assert out.n == 2
    assert out.mape == pytest.approx(0.1)
    expected_rmse = math.sqrt((math.log(1.1) ** 2 + math.log(0.9) ** 2) / 2)
    assert out.rmse_log == pytest.approx(expected_rmse)


def test_ratio_metrics_known_cod_and_cleaning():
    out = ratio_metrics([90_000.0, 100_000.0, 110_000.0], [100_000.0] * 3)
    assert out.median_ratio == pytest.approx(1.0)
    assert out.cod == pytest.approx(6.6667, abs=0.01)

    cleaned = fit_metrics([100.0, float("nan"), -5.0], [100.0, 100.0, 100.0])
    assert cleaned.n == 1


def _synthetic_mart(n=800, seed=42, cash_fraction=0.0, cash_discount=0.30):
    rng = np.random.default_rng(seed)
    start = datetime(2016, 1, 1)
    area = rng.uniform(800, 2400, n)
    zips = rng.choice(["19106", "19147", "19125"], n)
    zip_factor = np.select([zips == "19106", zips == "19147"], [1.4, 1.1], default=0.9)
    price = 150.0 * area * zip_factor * np.exp(rng.normal(0, 0.12, n))  # market value
    is_cash = rng.random(n) < cash_fraction
    sale_price = np.where(is_cash, price * (1.0 - cash_discount), price)  # cash sells low
    block_roll = price * np.exp(rng.normal(0, 0.08, n))
    asmt = price * rng.uniform(0.75, 1.15, n)

    numeric, categorical = feature_lists(time_adjusted=False)
    rows = []
    for i in range(n):
        row = dict.fromkeys(numeric, 0.0)
        row.update(dict.fromkeys(categorical, "x"))
        row.update(
            {
                "sale_id": f"s{i}",
                "parcel_id": f"p{i}",
                "sale_date": start + timedelta(days=3 * i),
                "sale_price": float(sale_price[i]),
                "fin_cash_sale": float(is_cash[i]),
                "time_adj_log": 0.0,
                "asmt_market_value_sale_year": float(asmt[i]),
                "char_livable_area": float(area[i]),
                "char_lot_area": float(area[i] * 0.8),
                "char_beds": float(rng.integers(2, 5)),
                "char_baths": 1.0,
                "char_year_built": 1925.0,
                "mkt_block_roll_mean_price": float(block_roll[i]),
                "mkt_block_roll_ppsf": float(block_roll[i] / area[i]),
                "mkt_block_roll_n": 5.0,
                "mkt_knn_log_ppsf": float(np.log(150.0 * zip_factor[i])),
                "mkt_knn_n": 10.0,
                "mkt_knn_mean_dist_m": 80.0,
                "char_new_build": 0.0,
                "mkt_newbuild_knn_log_ppsf": None,
                "mkt_newbuild_knn_n": 0.0,
                "mkt_newbuild_knn_mean_dist_m": None,
                "mkt_newbuild_premium": 0.0,
                "mkt_area_level_log_ppsf": float(np.log(zip_factor[i])),
                "loc_lon": float(-75.15 + rng.normal(0, 0.01)),
                "loc_lat": float(39.95 + rng.normal(0, 0.01)),
                "time_quarter": float(((start + timedelta(days=3 * i)).month - 1) // 3 + 1),
                "time_month": float((start + timedelta(days=3 * i)).month),
                "char_category": "SINGLE FAMILY",
                "char_building_type": "ROW TYPICAL",
                "char_style": "row",
                "char_era": "1920s_30s",
                "char_exterior_condition": "4",
                "char_interior_condition": "4",
                "char_quality_grade_raw": "C",
                "char_basement": "D",
                "char_central_air": "N",
                "char_heater": "H",
                "char_construction": "A",
                "char_view": "I",
                "char_topography": "F",
                "loc_zip5": str(zips[i]),
                "loc_ward": "05",
                "loc_census_tract_raw": "001",
                "loc_market_area": f"ma_{zips[i]}",
                "loc_district": "d_00",
            }
        )
        row.pop("time_sale_epoch_days")  # derived inside the trainer
        rows.append(row)
    return pl.DataFrame(rows)


def test_train_baseline_end_to_end(tmp_path):
    frame = _synthetic_mart()
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )

    result = train_baseline(
        tmp_path,
        test_fraction=0.15,
        lgb_params={"num_leaves": 15, "min_data_in_leaf": 5, "learning_rate": 0.1},
        num_boost_round=300,
        early_stopping_rounds=30,
    )

    assert set(result.overall) == {"lightgbm", "ridge", "opa_assessment"}
    lgb_overall = result.overall["lightgbm"]
    assert lgb_overall["n"] == 120
    assert lgb_overall["r2_log"] > 0.3
    assert 0.8 < lgb_overall["median_ratio"] < 1.2
    assert result.overall["opa_assessment"]["cod"] is not None

    for artifact in (
        "model_lightgbm.txt",
        "model_lightgbm_q05.txt",
        "model_lightgbm_q95.txt",
        "params.json",
        "categorical_mappings.json",
        "evaluation.parquet",
        "feature_importance.parquet",
        "predictions.parquet",
        "run.manifest.json",
    ):
        assert (result.run_dir / artifact).exists()

    # the CQR quantile heads score in order and bracket sensibly
    from philly_fair_measure.models.scoring import score_quantile_heads

    bands = score_quantile_heads(result.run_dir, _synthetic_mart().tail(120))
    assert bands is not None
    q_lo, q_hi = bands
    assert (q_lo <= q_hi).all()
    assert float(np.median(q_hi - q_lo)) > 0.01  # a real band, not a collapsed one

    predictions = pl.read_parquet(result.run_dir / "predictions.parquet")
    assert predictions.height == 120
    # out-of-time split: every test sale is later than the training cutoff implies
    assert predictions["sale_date"].min() > datetime(2021, 6, 1)

    # both ratio-study conventions and style segments are reported
    evaluation = result.evaluation
    conventions = set(evaluation["convention"].unique().to_list())
    assert conventions == {"out_of_time", "time_adjusted"}
    assert "style" in evaluation["segment_type"].unique().to_list()

    # scoring from the persisted run reproduces training-time predictions
    from philly_fair_measure.models.scoring import score_lightgbm

    frame_scored = (
        _synthetic_mart()
        .tail(120)
        .with_columns(
            (pl.col("sale_date") - pl.datetime(1997, 1, 1))
            .dt.total_days()
            .alias("time_sale_epoch_days")
        )
    )
    scored = score_lightgbm(result.run_dir, frame_scored)
    np.testing.assert_allclose(scored, predictions["pred_lightgbm"].to_numpy(), rtol=1e-6)


def test_calibrate_on_financed_shifts_toward_market_value(tmp_path):
    import time as _time

    # 40% cash sales at a 30% discount; enough rows that the financed val slice
    # (~0.6 * 0.1 * 0.85 * n) clears _MIN_CALIBRATION_ROWS so the path engages.
    frame = _synthetic_mart(n=6000, cash_fraction=0.4, cash_discount=0.30)
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )
    params = dict(
        test_fraction=0.15,
        lgb_params={"num_leaves": 15, "min_data_in_leaf": 5, "learning_rate": 0.1},
        num_boost_round=300,
        early_stopping_rounds=30,
    )
    res_all = train_baseline(tmp_path, calibrate_on_financed=False, **params)
    _time.sleep(1.1)  # second-resolution run_id must differ
    res_fin = train_baseline(tmp_path, calibrate_on_financed=True, **params)

    # centering on financed lifts predictions to market value, so ratios vs the
    # cash-blended sale prices rise (cash homes now assessed above their low price)
    assert (
        res_fin.overall["lightgbm"]["median_ratio"]
        > res_all.overall["lightgbm"]["median_ratio"] + 0.02
    )
