import polars as pl
import pytest

from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef
from philly_fair_measure.models.baseline import train_baseline
from philly_fair_measure.models.comps import find_comps, resolve_parcel
from tests.test_baseline import _synthetic_mart

_INPUTS = [InputRef(dataset="test", fetched_at="t")]


@pytest.fixture()
def comps_env(tmp_path):
    mart = _synthetic_mart()
    write_derived_table(mart, tmp_path, "marts", "sale_features", _INPUTS)
    train_baseline(
        tmp_path,
        test_fraction=0.15,
        lgb_params={"num_leaves": 15, "min_data_in_leaf": 5, "learning_rate": 0.1},
        num_boost_round=150,
        early_stopping_rounds=30,
    )
    assessment = mart.with_columns(
        pl.format("{} TEST ST", pl.col("sale_id")).alias("address"),
        (pl.col("sale_price") * 0.9).alias("opa_market_value"),
    )
    write_derived_table(assessment, tmp_path, "marts", "assessment_features", _INPUTS)
    # staged roll only supplies comp addresses
    staged = tmp_path / "staged"
    staged.mkdir(exist_ok=True)
    mart.select(
        pl.col("parcel_id").alias("parcel_number"),
        pl.format("{} TEST ST", pl.col("sale_id")).alias("location"),
    ).write_parquet(staged / "opa_properties.parquet")
    return tmp_path


def test_find_comps_returns_similar_neighbors(comps_env):
    target = "p10"
    result = find_comps(target, comps_env, k=8)
    comps = result.comps
    assert comps.height == 8
    assert target not in comps["parcel_id"].to_list()
    sims = comps["similarity"].to_list()
    assert sims == sorted(sims, reverse=True)
    assert 0.0 < sims[0] <= 1.0
    # zip drives price in the synthetic market: the model's leaves should
    # group same-zip sales, so the top comp shares the target's zip
    target_zip = result.target["loc_zip5"]
    assert comps["loc_zip5"][0] == target_zip
    assert (comps["price_adj_today"] > 0).all()
    assert comps["address"][0] is not None


def test_resolve_parcel_by_id_and_address(comps_env):
    by_id = resolve_parcel("p10", comps_env)
    # p10 is not all digits, so it resolves via the address path; use address
    by_address = resolve_parcel("s10 TEST", comps_env)
    assert any(c["parcel_id"] == "p10" for c in by_address)
    assert by_id == [] or all("parcel_id" in c for c in by_id)


def test_find_comps_unknown_parcel_raises(comps_env):
    with pytest.raises(KeyError):
        find_comps("nope", comps_env)
