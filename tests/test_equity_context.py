import polars as pl
import pytest

from philly_fair_measure.equity_context import equity_context
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef


def _screen(tmp_path):
    # one ZIP of ~100 homes ~$200k with ratios tightly around 1.0, plus a clear
    # over- and under-assessed home
    rows = [
        {
            "parcel_id": f"p{i}",
            "model_family": "residential",
            "loc_zip5": "19100",
            "model_median": 200_000.0,
            "opa_market_value": 200_000.0 * (0.95 + 0.001 * i),  # ~0.95..1.045
        }
        for i in range(100)
    ]
    rows += [
        {
            "parcel_id": "over",
            "model_family": "residential",
            "loc_zip5": "19100",
            "model_median": 200_000.0,
            "opa_market_value": 320_000.0,
        },  # ratio 1.60
        {
            "parcel_id": "under",
            "model_family": "residential",
            "loc_zip5": "19100",
            "model_median": 200_000.0,
            "opa_market_value": 100_000.0,
        },  # ratio 0.50
    ]
    df = pl.DataFrame(rows).with_columns(
        (pl.col("opa_market_value") / pl.col("model_median")).alias("opa_vs_model_ratio")
    )
    write_derived_table(
        df, tmp_path, "marts", "assessment_screen", [InputRef(dataset="t", fetched_at="t")]
    )
    return df


def test_equity_context_flags_over_and_under(tmp_path):
    df = _screen(tmp_path)

    over = equity_context(
        df.filter(pl.col("parcel_id") == "over").to_dicts()[0], tmp_path, min_peers=20
    )
    under = equity_context(
        df.filter(pl.col("parcel_id") == "under").to_dicts()[0], tmp_path, min_peers=20
    )

    assert over is not None
    assert over.verdict == "over" and over.percentile > 90
    assert over.peer_median_ratio == pytest.approx(1.0, abs=0.05)
    assert "similar value" in over.peer_label

    assert under is not None
    assert under.verdict == "under" and under.percentile < 10


def test_equity_context_none_without_ratio(tmp_path):
    _screen(tmp_path)
    row = {"parcel_id": "x", "loc_zip5": "19100", "model_median": None, "opa_vs_model_ratio": None}
    assert equity_context(row, tmp_path, min_peers=20) is None
