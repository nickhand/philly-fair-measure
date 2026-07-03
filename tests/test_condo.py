from datetime import datetime

import polars as pl
import pytest

from philly_assessments.features.condo_features import assemble_condo_features


def _unit(parcel, area=900.0, street="777", hn=200, lon=-75.16, lat=39.95):
    return {
        "parcel_number": parcel,
        "category_code_description": "SINGLE FAMILY",
        "building_code_description": "RES CONDO 5+ STY MASONRY",
        "location": f"{hn} MAIN ST",
        "unit": "2204",
        "market_value": 250_000.0,
        "geographic_ward": "05",
        "total_livable_area": area,
        "number_of_bedrooms": 2,
        "number_of_bathrooms": 1,
        "year_built_parsed": 1980,
        "exterior_condition": "4",
        "interior_condition": "4",
        "quality_grade": "C",
        "zip_code": "19106",
        "street_code": street,
        "house_number_parsed": hn,
        "lon": lon,
        "lat": lat,
        "lonlat_status": "ok",
    }


def _sale(sale_id, parcel, price, date, status="arms_length"):
    return {
        "sale_id": sale_id,
        "parcel_id": parcel,
        "sale_date": date,
        "sale_price": price,
        "sale_year": date.year,
        "validity_status": status,
    }


def test_condo_features_building_roll_and_shares():
    units = [
        _unit("880000001", area=1000.0),
        _unit("880000002", area=1000.0),
        _unit("880000003", area=2000.0),
        _unit("880000009", street="999", hn=50, lon=-75.10),  # different building
    ]
    sales = [
        _sale("a", "880000001", 300_000.0, datetime(2020, 1, 1)),
        _sale("a2", "880000001", 310_000.0, datetime(2021, 6, 1)),  # same unit resale
        _sale("b", "880000002", 320_000.0, datetime(2021, 1, 1)),
        _sale("c", "880000003", 640_000.0, datetime(2022, 1, 1)),
        _sale("bad", "880000002", 900_000.0, datetime(2021, 3, 1), status="suspect"),
        _sale("res", "123456789", 250_000.0, datetime(2021, 1, 1)),  # non-condo: excluded
    ]
    out = assemble_condo_features(
        pl.LazyFrame(sales),
        pl.LazyFrame(units),
        assessments=pl.LazyFrame(
            [{"parcel_number": "880000003", "year_parsed": 2022, "market_value": 500_000.0}]
        ),
        min_sale_year=2014,
    )
    by = {r["sale_id"]: r for r in out.to_dicts()}
    assert "res" not in by and "bad" not in by

    # unit-area share: 1000 / (1000+1000+2000)
    assert by["a"]["unit_area_share"] == pytest.approx(0.25)
    assert by["c"]["unit_area_share"] == pytest.approx(0.5)
    assert by["a"]["bldg_n_units"] == 3

    # building rolling mean for c: prior sales in building from OTHER units only
    # (a, a2 same unit -> both count; a2 excluded? no: a/a2 are unit 001, b is 002;
    # c is unit 003 so peers = a, a2, b)
    assert by["c"]["mkt_bldg_roll_n"] == 3
    # first sale in the building sees nothing
    assert by["a"]["mkt_bldg_roll_n"] == 0
    # a2 (resale of unit 001) must NOT see its own earlier sale `a`, only b
    assert by["a2"]["mkt_bldg_roll_n"] == 1
    assert by["a2"]["mkt_bldg_roll_mean_price"] == pytest.approx(320_000.0)

    # OPA benchmark joined for the sale year
    assert by["c"]["asmt_market_value_sale_year"] == 500_000.0
    assert by["a"]["asmt_market_value_sale_year"] is None

    # floor parsed from the unit token (fixture unit "2204" -> floor 22)
    assert by["a"]["char_floor"] == 22


def test_floor_expr_conventions():
    import polars as pl

    from philly_assessments.features.condo_features import floor_expr

    out = pl.DataFrame(
        {"unit": ["2204", "8L", "33K", "PH", "P209", "3", "9901", None, "CD"]}
    ).with_columns(floor_expr())
    assert out["char_floor"].to_list() == [22, 8, 33, None, 2, 3, None, None, None]


def test_condo_assessment_features_loo_at_date():
    from philly_assessments.features.condo_features import assemble_condo_assessment_features

    units = [
        _unit("880000001", area=1000.0),
        _unit("880000002", area=1000.0),
        _unit("880000009", street="999", hn=50, lon=-75.10),  # different building
        _unit("880000777", area=100_000.0),  # whole-building account: out of scope
    ]
    sales = [
        _sale("s1", "880000001", 300_000.0, datetime(2024, 1, 1)),
        _sale("s2", "880000002", 400_000.0, datetime(2024, 6, 1)),
        _sale("s9", "880000009", 200_000.0, datetime(2024, 3, 1)),
        _sale("bulk", "880000777", 90_000_000.0, datetime(2024, 2, 1)),
    ]
    out = assemble_condo_assessment_features(
        pl.LazyFrame(units), pl.LazyFrame(sales), datetime(2025, 1, 1)
    )
    by = {r["parcel_id"]: r for r in out.to_dicts()}
    assert "880000777" not in by  # area ceiling excludes whole-building accounts

    # unit 1: sees only unit 2's sale (own sale subtracted)
    assert by["880000001"]["mkt_bldg_roll_n"] == 1
    assert by["880000001"]["mkt_bldg_roll_mean_price"] == pytest.approx(400_000.0)
    # unit 2 symmetric
    assert by["880000002"]["mkt_bldg_roll_n"] == 1
    assert by["880000002"]["mkt_bldg_roll_mean_price"] == pytest.approx(300_000.0)
    # screen columns present
    assert by["880000001"]["opa_market_value"] == 250_000.0
    assert by["880000001"]["address"] == "200 MAIN ST"
    assert by["880000001"]["loc_ward"] == "05"
