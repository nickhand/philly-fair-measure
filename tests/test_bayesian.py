import numpy as np
import polars as pl
import pytest

from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import InputRef
from philly_assessments.models.bayesian import (
    CONDO_SPEC,
    CovariateEncoder,
    GeoIndex,
    RBFBasis,
    _sigma_design,
    train_bayesian,
)
from tests.test_baseline import _synthetic_mart


def _frame():
    return pl.DataFrame(
        {
            "char_livable_area": [1000.0, 2000.0, None],
            "char_lot_area": [800.0, 1600.0, 800.0],
            "mkt_block_roll_mean_price": [200_000.0, None, 400_000.0],
            "mkt_block_roll_ppsf": [180.0, None, 300.0],
            "char_beds": [3.0, 4.0, 3.0],
            "char_baths": [1.0, 2.0, 1.0],
            "char_year_built": [1920.0, 1950.0, None],
            "mkt_knn_log_ppsf": [5.2, 5.6, None],
            "mkt_area_level_log_ppsf": [0.1, -0.2, 0.0],
            "mkt_knn_mean_dist_m": [40.0, 90.0, None],
            "mkt_parcel_prev_log_price_ref": [12.1, None, 12.6],
            "char_exterior_condition": ["4", "3", None],
            "char_interior_condition": ["4", None, "5"],
            "loc_market_area": ["ma_001", "ma_001", "ma_002"],
            "loc_district": ["d_00", "d_00", "d_01"],
        }
    )


def test_covariate_encoder_imputes_and_standardizes():
    df = _frame()
    encoder = CovariateEncoder.fit(df)
    x = encoder.transform(df)
    assert x.shape == (3, len(encoder.feature_names))
    assert np.isfinite(x).all()
    # two trailing missing indicators: block roll, then prev price
    assert encoder.feature_names[-2:] == ["block_roll_missing", "prev_price_missing"]
    assert x[:, encoder.feature_names.index("block_roll_missing")].tolist() == [0.0, 1.0, 0.0]
    assert x[:, encoder.feature_names.index("prev_price_missing")].tolist() == [0.0, 1.0, 0.0]
    assert abs(x[:, 0].mean()) < 1e-9


def test_covariate_encoder_survives_float_nan():
    # float NaN (e.g. upstream 0/0) must be treated as missing, not poison
    # the column's mean/std (regression: first v2 training run failed on this)
    df = _frame().with_columns(pl.Series("mkt_block_roll_ppsf", [float("nan"), 180.0, 300.0]))
    encoder = CovariateEncoder.fit(df)
    x = encoder.transform(df)
    assert np.isfinite(x).all()


def test_condo_family_spec_encoder_and_sigma():
    df = pl.DataFrame(
        {
            "char_unit_area": [700.0, 1200.0, None],
            "mkt_bldg_roll_mean_price": [300_000.0, None, 500_000.0],
            "mkt_bldg_roll_ppsf": [350.0, None, 420.0],
            "bldg_n_units": [24.0, 8.0, 150.0],
            "char_beds": [1.0, 2.0, 2.0],
            "char_baths": [1.0, 2.0, None],
            "char_year_built": [1985.0, 2005.0, 1920.0],
            "char_floor": [3.0, None, 12.0],
            "unit_area_share": [0.02, 0.1, None],
            "mkt_knn_log_ppsf": [5.8, 6.0, None],
            "mkt_area_level_log_ppsf": [0.2, -0.1, 0.0],
            "mkt_knn_mean_dist_m": [60.0, 200.0, None],
            "char_exterior_condition": ["4", None, "3"],
            "char_interior_condition": ["4", "3", None],
        }
    )
    encoder = CovariateEncoder.fit(df, CONDO_SPEC)
    assert encoder.family == "condo"
    # one trailing missing indicator: the building roll (no prev-price analog)
    assert encoder.feature_names[-1] == "bldg_roll_missing"
    assert "log_unit_area" in encoder.feature_names
    x = encoder.transform(df)
    assert x.shape == (3, len(encoder.feature_names))
    assert np.isfinite(x).all()
    assert x[:, encoder.feature_names.index("bldg_roll_missing")].tolist() == [0.0, 1.0, 0.0]
    # condo sigma design: evidence terms only, no style dummies
    z = _sigma_design(df, "condo")
    assert z.shape == (3, len(CONDO_SPEC.sigma_terms))
    assert np.isfinite(z).all()
    # runs persisted before families existed load as residential
    assert CovariateEncoder(names=[], medians={}, means={}, stds={}).family == "residential"


def test_parcel_index_repeats_only_and_leakage_safe():
    from philly_assessments.models.bayesian import ParcelIndex

    train = pl.DataFrame(
        {"parcel_id": ["a", "a", "b", "b", "b", "c"]}  # a x2, b x3, c x1
    )
    pidx = ParcelIndex.fit(train, min_sales=2)
    assert pidx.parcels == ["a", "b"]  # singleton c excluded (unidentified)
    assert pidx.n == 2

    # mapped: singleton/unseen -> the zero slot (n); test parcel 'd' never seen
    test = pl.DataFrame({"parcel_id": ["a", "b", "c", "d"]})
    assert pidx.mapped(test).tolist() == [0, 1, 2, 2]  # c,d -> zero slot (n=2)
    # seen: known repeat -> index, else -1 (scoring marginalizes these)
    assert pidx.seen(test).tolist() == [0, 1, -1, -1]


def test_geo_index_maps_unseen_geography():
    geo = GeoIndex.fit(_frame())
    assert set(geo.fine) == {"ma_001", "ma_002"}
    new = pl.DataFrame(
        {
            "loc_market_area": ["ma_001", "ma_999", "ma_999"],
            "loc_district": ["d_00", "d_01", "d_99"],
        }
    )
    fine, coarse = geo.indices(new)
    assert fine.tolist() == [geo.fine.index("ma_001"), -1, -1]
    assert coarse.tolist()[0] == geo.coarse.index("d_00")
    assert coarse.tolist()[1] == geo.coarse.index("d_01")
    assert coarse.tolist()[2] == -1


def test_rbf_basis_is_smooth_and_bounded():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 10_000, size=(500, 2))
    basis = RBFBasis.fit(xy, n_centers=16, seed=0)
    b = basis.transform(xy)
    assert b.shape == (500, 16)
    assert (b > 0).all() and (b <= 1.0 + 1e-12).all()
    # a point exactly at a center activates that basis function fully
    at_center = basis.transform(basis.centers[:1])
    assert at_center[0, 0] == pytest.approx(1.0)


@pytest.mark.slow
def test_train_bayesian_end_to_end(tmp_path):
    frame = _synthetic_mart(n=400)
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )
    result = train_bayesian(tmp_path, test_fraction=0.15, draws=150, tune=150, chains=2, seed=7)
    row = result.overall
    assert row["n"] == 60
    assert row["r2_log"] is not None and row["r2_log"] > 0.2
    assert 0.75 <= row["coverage_90"] <= 1.0
    for artifact in (
        "posterior_summary.parquet",
        "posterior_draws.npz",
        "covariates.json",
        "geography.json",
    ):
        assert (result.run_dir / artifact).exists()
    # spatial basis is off by default (measured >15x sampling cost)
    assert not (result.run_dir / "rbf.json").exists()
    predictions = pl.read_parquet(result.run_dir / "predictions.parquet")
    assert predictions.height == 60
    assert (predictions["pi_high_90"] > predictions["pi_low_90"]).all()

    # scoring artifacts roundtrip: price a few rows through the scoring path
    from philly_assessments.models.scoring import score_bayesian_intervals

    subset = frame.head(5)
    median, lo, hi = score_bayesian_intervals(result.run_dir, subset, chunk_size=3, seed=1)
    assert len(median) == 5
    assert np.isfinite(median).all() and (median > 0).all()
    assert (hi > lo).all()
