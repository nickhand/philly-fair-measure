import numpy as np
import polars as pl
import pytest

from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import InputRef
from philly_assessments.models.bayesian import CovariateEncoder, GeoIndex, train_bayesian
from tests.test_baseline import _synthetic_mart


def _frame():
    return pl.DataFrame(
        {
            "char_livable_area": [1000.0, 2000.0, None],
            "char_lot_area": [800.0, 1600.0, 800.0],
            "mkt_block_roll_mean_price": [200_000.0, None, 400_000.0],
            "char_beds": [3.0, 4.0, 3.0],
            "char_baths": [1.0, 2.0, 1.0],
            "char_year_built": [1920.0, 1950.0, None],
            "time_sale_epoch_days": [9000.0, 9100.0, 9200.0],
            "char_exterior_condition": ["4", "3", None],
            "char_interior_condition": ["4", None, "5"],
            "loc_census_tract_raw": ["t1", "t1", "t2"],
            "loc_ward": ["w1", "w1", "w2"],
        }
    )


def test_covariate_encoder_imputes_and_standardizes():
    df = _frame()
    encoder = CovariateEncoder.fit(df)
    x = encoder.transform(df)
    assert x.shape == (3, len(encoder.feature_names))
    assert np.isfinite(x).all()  # imputation leaves no NaN
    assert encoder.feature_names[-1] == "block_roll_missing"
    assert x[:, -1].tolist() == [0.0, 1.0, 0.0]
    # standardized columns have ~zero mean on the fitting frame
    assert abs(x[:, 0].mean()) < 1e-9


def test_geo_index_maps_unseen_geography():
    df = _frame()
    geo = GeoIndex.fit(df)
    assert set(geo.tracts) == {"t1", "t2"}
    new = pl.DataFrame(
        {"loc_census_tract_raw": ["t1", "t9", "t9"], "loc_ward": ["w1", "w2", "w9"]}
    )
    tract, ward = geo.tract_indices(new)
    assert tract.tolist() == [geo.tracts.index("t1"), -1, -1]
    assert ward.tolist()[0] == geo.wards.index("w1")
    assert ward.tolist()[1] == geo.wards.index("w2")
    assert ward.tolist()[2] == -1


@pytest.mark.slow
def test_train_bayesian_end_to_end(tmp_path):
    frame = _synthetic_mart(n=400)
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )
    result = train_bayesian(
        tmp_path, test_fraction=0.15, draws=150, tune=150, chains=2, seed=7
    )
    row = result.overall
    assert row["n"] == 60
    assert row["r2_log"] is not None and row["r2_log"] > 0.2
    assert 0.75 <= row["coverage_90"] <= 1.0  # roughly calibrated even on a tiny run
    assert (result.run_dir / "posterior_summary.parquet").exists()
    predictions = pl.read_parquet(result.run_dir / "predictions.parquet")
    assert predictions.height == 60
    assert (predictions["pi_high_90"] > predictions["pi_low_90"]).all()
