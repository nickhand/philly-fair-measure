import numpy as np
import polars as pl

from philly_fair_measure.models.conformal import (
    CalibrationSet,
    _split_quantiles,
    calibration_from_run,
    conformal_offsets,
    frame_residuals,
    split_frames,
)


def test_split_quantiles_finite_sample_correction():
    r = np.arange(1.0, 100.0)  # n=99: residuals 1..99
    lo, hi = _split_quantiles(r, alpha=0.10)
    # upper index ceil(100 * 0.95) = 95th smallest; lower mirrors to the 5th
    assert hi == 95.0
    assert lo == 5.0
    assert _split_quantiles(np.array([]), alpha=0.10) == (-np.inf, np.inf)


def test_global_coverage_iid():
    rng = np.random.default_rng(0)
    n_cal, n_test = 4000, 8000
    cal = CalibrationSet(
        residual=rng.normal(0, 1, n_cal),
        xy=np.full((n_cal, 2), np.nan),
        district=np.array([""] * n_cal),
    )
    lo, hi = conformal_offsets(
        cal, np.full((n_test, 2), np.nan), np.array([""] * n_test), method="global"
    )
    covered = (rng.normal(0, 1, n_test) >= lo) & (rng.normal(0, 1, n_test) <= hi)
    # NB: two independent draws is fine here — coverage is a marginal property
    assert 0.88 <= covered.mean() <= 0.92


def test_knn_adapts_to_spatial_heteroscedasticity():
    rng = np.random.default_rng(1)

    def make(n):
        xy = rng.uniform(0, 2000, (n, 2))
        sigma = np.where(xy[:, 0] < 1000, 0.1, 0.5)
        return xy, rng.normal(0, sigma)

    xy_cal, r_cal = make(6000)
    xy_test, r_test = make(4000)
    cal = CalibrationSet(residual=r_cal, xy=xy_cal, district=np.array([""] * 6000))
    lo, hi = conformal_offsets(
        cal, xy_test, np.array([""] * 4000), method="knn", k=300, softening_m=100.0
    )
    covered = (r_test >= lo) & (r_test <= hi)
    assert 0.87 <= covered.mean() <= 0.93
    # intervals must be locally adaptive: wide in the noisy east, tight in the west
    west = xy_test[:, 0] < 800
    east = xy_test[:, 0] > 1200
    assert np.median((hi - lo)[east]) > 2.5 * np.median((hi - lo)[west])
    # rows without coordinates fall back to finite global offsets
    lo_nan, hi_nan = conformal_offsets(
        cal, np.full((3, 2), np.nan), np.array([""] * 3), method="knn"
    )
    assert np.isfinite(lo_nan).all() and np.isfinite(hi_nan).all()


def test_district_mondrian_with_fallback():
    rng = np.random.default_rng(2)
    n = 2000
    district = np.array(["d_wide"] * n + ["d_tight"] * n)
    residual = np.concatenate([rng.normal(0, 0.5, n), rng.normal(0, 0.05, n)])
    cal = CalibrationSet(residual=residual, xy=np.full((2 * n, 2), np.nan), district=district)

    targets = np.array(["d_wide", "d_tight", "d_unseen", ""])
    lo, hi = conformal_offsets(
        cal, np.full((4, 2), np.nan), targets, method="district", min_group=200
    )
    g_lo, g_hi = _split_quantiles(residual, 0.10)
    assert hi[0] - lo[0] > 4 * (hi[1] - lo[1])  # per-district widths
    assert (lo[2], hi[2]) == (g_lo, g_hi)  # unseen -> global
    assert (lo[3], hi[3]) == (g_lo, g_hi)  # missing -> global


def test_calibration_and_coverage_from_trained_run(tmp_path):
    from philly_fair_measure.ingest.derived import write_derived_table
    from philly_fair_measure.ingest.manifests import InputRef
    from philly_fair_measure.models.baseline import train_baseline
    from tests.test_baseline import _synthetic_mart

    frame = _synthetic_mart()
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )
    result = train_baseline(
        tmp_path,
        test_fraction=0.15,
        lgb_params={"num_leaves": 15, "min_data_in_leaf": 5, "learning_rate": 0.1},
        num_boost_round=200,
        early_stopping_rounds=30,
    )

    fit_df, val_df, test_df = split_frames(result.run_dir, tmp_path)
    assert fit_df.height + val_df.height + test_df.height == 800
    assert test_df.height == 120
    # the rebuilt test slice is the same one the trainer evaluated on
    predictions = pl.read_parquet(result.run_dir / "predictions.parquet")
    assert test_df["sale_id"].to_list() == predictions["sale_id"].to_list()

    cal = calibration_from_run(result.run_dir, tmp_path)
    assert cal.residual.size == val_df.height

    test_resid = frame_residuals(result.run_dir, test_df)
    from philly_fair_measure.models.conformal import xy_district

    xy, district = xy_district(test_df)
    lo, hi = conformal_offsets(cal, xy, district, method="knn", k=50)
    assert np.isfinite(lo).all() and np.isfinite(hi).all()
    assert (hi > lo).all()
    covered = (test_resid >= lo) & (test_resid <= hi)
    # loose bound: 68-point calibration set, but must be in the right regime
    assert covered.mean() >= 0.75
