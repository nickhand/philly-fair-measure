from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from philly_assessments.features.market_areas import build_market_areas, sale_points
from philly_assessments.features.price_index import (
    CITYWIDE,
    build_price_index,
    with_time_adjustment,
)
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import InputRef

_INPUTS = [InputRef(dataset="test", fetched_at="t")]

# two spatial blobs ~2km apart: west expensive, east cheap
_WEST = (-75.16, 39.95)
_EAST = (-75.14, 39.95)


def _opa_row(parcel, lon, lat, area=1200.0, status="ok", category="SINGLE FAMILY"):
    return {
        "parcel_number": parcel,
        "lon": lon,
        "lat": lat,
        "lonlat_status": status,
        "total_livable_area": area,
        "category_code_description": category,
    }


def _sale(sale_id, parcel, price, date, status="arms_length"):
    return {
        "sale_id": sale_id,
        "parcel_id": parcel,
        "sale_date": date,
        "sale_price": price,
        "validity_status": status,
    }


def _blob_data(rng, n_per_blob=60):
    opa, sales = [], []
    start = datetime(2022, 1, 1)
    for i in range(n_per_blob):
        for blob, (lon0, lat0), price in (("w", _WEST, 480_000.0), ("e", _EAST, 120_000.0)):
            parcel = f"{blob}{i}"
            opa.append(_opa_row(parcel, lon0 + rng.normal(0, 0.001), lat0 + rng.normal(0, 0.001)))
            sales.append(
                _sale(
                    f"s_{parcel}",
                    parcel,
                    price * rng.uniform(0.9, 1.1),
                    start + timedelta(days=6 * i),
                )
            )
    return opa, sales


def _write_inputs(tmp_path, opa_rows, sale_rows):
    write_derived_table(pl.DataFrame(opa_rows), tmp_path, "staged", "opa_properties", _INPUTS)
    write_derived_table(pl.DataFrame(sale_rows), tmp_path, "marts", "sale_validity", _INPUTS)


def test_sale_points_filters():
    opa = [
        _opa_row("p1", *_WEST),
        _opa_row("p2", *_EAST, status="missing"),  # unlocated
        _opa_row("p3", *_WEST, area=50.0),  # implausible area
    ]
    sales = [
        _sale("s1", "p1", 300_000.0, datetime(2023, 1, 5)),
        _sale("s2", "p1", 300_000.0, datetime(2023, 2, 5), status="suspect"),  # excluded
        _sale("s3", "p2", 300_000.0, datetime(2023, 1, 5)),  # unlocated parcel
        _sale("s4", "p3", 300_000.0, datetime(2023, 1, 5)),  # bad area
    ]
    points = sale_points(pl.LazyFrame(sales), pl.LazyFrame(opa))
    assert points["sale_id"].to_list() == ["s1"]
    assert points["month"].to_list() == [datetime(2023, 1, 1)]


def test_build_market_areas_recovers_blobs(tmp_path):
    rng = np.random.default_rng(3)
    opa, sales = _blob_data(rng)
    # unsold parcels near each blob + one unlocated
    opa += [
        _opa_row("unsold_w", _WEST[0] + 0.0005, _WEST[1]),
        _opa_row("unsold_e", _EAST[0] - 0.0005, _EAST[1]),
        _opa_row("nowhere", None, None, status="missing"),
    ]
    _write_inputs(tmp_path, opa, sales)

    result = build_market_areas(tmp_path, n_areas=2, n_districts=2, seed=1)
    frame = pl.read_parquet(result.path)
    by_id = {row["parcel_id"]: row for row in frame.to_dicts()}

    west_area = by_id["w0"]["market_area"]
    east_area = by_id["e0"]["market_area"]
    assert west_area != east_area
    # all west parcels share an area; unsold parcels inherit their neighborhood
    assert all(by_id[f"w{i}"]["market_area"] == west_area for i in range(60))
    assert by_id["unsold_w"]["market_area"] == west_area
    assert by_id["unsold_e"]["market_area"] == east_area
    assert by_id["nowhere"]["market_area"] is None
    # area stats present and ordered as expected (west pricier)
    assert by_id["w0"]["ma_med_adj_log_ppsf"] > by_id["e0"]["ma_med_adj_log_ppsf"]
    assert by_id["w0"]["ma_n_sales"] == 60


def test_price_index_recovers_drift_and_adjusts(tmp_path):
    rng = np.random.default_rng(5)
    start = datetime(2022, 1, 1)
    months = 24
    opa, sales, areas = [], [], []
    for d, (lon0, lat0), drift in (("d_00", _WEST, 0.02), ("d_01", _EAST, 0.0)):
        for i in range(80):
            parcel = f"{d}_p{i}"
            opa.append(_opa_row(parcel, lon0 + rng.normal(0, 0.001), lat0 + rng.normal(0, 0.001)))
            areas.append({"parcel_id": parcel, "market_area": "x", "district": d})
        for m in range(months):
            month_start = start + timedelta(days=31 * m)
            for j in range(100):
                parcel = f"{d}_p{j % 80}"
                base = 300_000.0 * np.exp(drift * m)
                sales.append(
                    _sale(
                        f"s_{d}_{m}_{j}",
                        parcel,
                        base * rng.uniform(0.95, 1.05),
                        month_start + timedelta(days=j % 27),
                    )
                )
    # a sale on a parcel with no district assignment must not duplicate the
    # citywide series (regression: null districts fill to CITYWIDE pre-grouping)
    opa.append(_opa_row("orphan", _WEST[0], _WEST[1] + 0.01))
    sales.append(_sale("s_orphan", "orphan", 250_000.0, start + timedelta(days=40)))

    _write_inputs(tmp_path, opa, sales)
    write_derived_table(pl.DataFrame(areas), tmp_path, "marts", "market_areas", _INPUTS)

    result = build_price_index(tmp_path)
    index = pl.read_parquet(result.path)
    assert set(index["district"].unique().to_list()) == {"d_00", "d_01", CITYWIDE}
    dupes = index.group_by("district", "month").len().filter(pl.col("len") > 1)
    assert dupes.height == 0

    # latest month is the reference: log_index ~ 0
    latest = index.sort("month").group_by("district").agg(pl.col("log_index").last())
    assert all(abs(v) < 1e-9 for v in latest["log_index"].to_list())

    # drifting district: first-month adjustment is large and positive;
    # shrinkage pulls it below the raw 2%/mo drift but well above half of it
    adjusted = with_time_adjustment(
        pl.DataFrame(
            {
                "loc_district": ["d_00", "d_01", "d_99", "d_00"],
                "sale_date": [start, start, start, datetime(2030, 1, 1)],
            }
        ),
        index,
        district_col="loc_district",
        date_col="sale_date",
    )
    adj = adjusted["time_adj_log"].to_list()
    total_drift = 0.02 * (months - 1)
    assert total_drift * 0.55 < adj[0] < total_drift * 1.05
    assert abs(adj[1]) < 0.12  # flat district: small adjustment
    assert adj[2] == pytest.approx((adj[0] + adj[1]) / 2, abs=0.15)  # citywide fallback between
    assert abs(adj[3]) < 1e-9  # future date clamps to reference month
