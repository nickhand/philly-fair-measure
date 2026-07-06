import polars as pl

from philly_fair_measure.staging.tables import stg_assessments, stg_deeds, stg_opa_properties
from philly_fair_measure.staging.temporal import with_parsed_timestamp, with_parsed_year


def test_with_parsed_timestamp_statuses():
    lf = pl.LazyFrame(
        {
            "sale_date": [
                "2023-05-01T00:00:00Z",  # ok
                None,  # missing
                "garbage",  # invalid
                "206-04-22T04:56:02Z",  # parses as year 206 -> implausible
            ]
        }
    )
    out = with_parsed_timestamp(lf, "sale_date").collect()
    assert out["sale_date_status"].to_list() == ["ok", "missing", "invalid", "implausible"]
    parsed = out["sale_date_parsed"].to_list()
    assert parsed[0] is not None
    assert parsed[1] is None and parsed[2] is None and parsed[3] is None
    # raw column untouched
    assert out["sale_date"].to_list()[3] == "206-04-22T04:56:02Z"


def test_with_parsed_year_statuses():
    lf = pl.LazyFrame({"year_built": ["1750", "0", None, "196Y", "2028"]})
    out = with_parsed_year(lf, "year_built").collect()
    assert out["year_built_status"].to_list() == [
        "ok",
        "implausible",  # sentinel zero
        "missing",
        "invalid",
        "ok",  # future year within bounds (2027 roll is already published)
    ]
    assert out["year_built_parsed"].to_list() == [1750, None, None, None, 2028]


def test_stg_assessments_dedupes_conflicting_keys():
    raw = pl.LazyFrame(
        {
            "cartodb_id": [1, 2, 3],
            "parcel_number": ["A", "A", "B"],
            "year": ["2024", "2024", "2024"],
            "market_value": [100.0, 200.0, 300.0],
            "taxable_land": [0.0, 0.0, 0.0],
            "taxable_building": [0.0, 0.0, 0.0],
            "exempt_land": [0.0, 0.0, 0.0],
            "exempt_building": [0.0, 0.0, 0.0],
        }
    )
    out = stg_assessments(raw).collect()
    assert out.height == 2
    row_a = out.filter(pl.col("parcel_number") == "A")
    # highest cartodb_id wins; ambiguity stays visible via key_copies
    assert row_a["market_value"].to_list() == [200.0]
    assert row_a["key_copies"].to_list() == [2]
    assert out.filter(pl.col("parcel_number") == "B")["key_copies"].to_list() == [1]
    assert out["year_parsed"].to_list() == [2024, 2024]


def _deed_row(**overrides):
    base = {
        "record_id": "r1",
        "document_id": 1,
        "document_type": "DEED",
        "opa_account_num": "123456789",
        "street_address": "108 ELFRETHS ALY",
        "zip_code": "19106",
        "display_date": "2023-05-01T00:00:00Z",
        "recording_date": "2023-05-10T00:00:00Z",
        "document_date": None,
        "cash_consideration": 405000.0,
        "other_consideration": 0.0,
        "total_consideration": 405000.0,
        "adjusted_total_consideration": 405000.0,
        "fair_market_value": 400000.0,
        "common_level_ratio": 1.0,
        "property_count": 1.0,
        "grantors": "SMITH JOHN",
        "grantees": "DOE JANE",
        "condo_name": None,
        "unit_num": None,
        "matched_regmap": "Y",
        "discrepancy": None,
    }
    base.update(overrides)
    return base


def test_stg_deeds_classifies_and_flags():
    raw = pl.LazyFrame(
        [
            _deed_row(record_id="r1"),
            _deed_row(record_id="r2", document_type="MORTGAGE"),  # filtered out
            _deed_row(record_id="r3", document_type="DEED SHERIFF", total_consideration=1.0),
            _deed_row(record_id="r4", document_type="DEED - DECEASED "),  # trailing space
            _deed_row(record_id="r5", property_count=3.0, opa_account_num=""),
            _deed_row(
                record_id="r6",
                display_date=None,
                document_date=None,
                recording_date="2020-01-01T00:00:00Z",
            ),
        ]
    )
    out = stg_deeds(raw).collect()
    assert out["record_id"].to_list() == ["r1", "r3", "r4", "r5", "r6"]
    by_id = {row["record_id"]: row for row in out.to_dicts()}
    assert by_id["r1"]["deed_kind"] == "standard"
    assert by_id["r1"]["sale_date_source"] == "display_date"
    assert by_id["r1"]["is_nominal"] is False
    assert by_id["r3"]["deed_kind"] == "sheriff"
    assert by_id["r3"]["is_nominal"] is True
    assert by_id["r4"]["deed_kind"] == "deceased"
    assert by_id["r5"]["is_multi_parcel"] is True
    assert by_id["r5"]["has_opa_link"] is False
    assert by_id["r6"]["sale_date_source"] == "recording_date"
    assert by_id["r6"]["sale_date"] is not None


def test_stg_deeds_recovers_condo_links_by_address_unit():
    raw = pl.LazyFrame(
        [
            # unit token in the address, no rtt link -> recovered
            _deed_row(
                record_id="c1",
                opa_account_num=None,
                street_address="1420 LOCUST ST APT 33K",
            ),
            # rtt's own unit_num field, hyphen + leading-zero variants normalize
            _deed_row(
                record_id="c2",
                opa_account_num=None,
                street_address="1420 LOCUST ST",
                unit_num="0-8L",
            ),
            # ambiguous (address, unit) on the OPA side -> NOT recovered
            _deed_row(
                record_id="c3",
                opa_account_num=None,
                street_address="200 LOCUST ST UNIT 5A",
            ),
            # native link untouched
            _deed_row(record_id="c4"),
            # no unit anywhere -> stays unlinked
            _deed_row(record_id="c5", opa_account_num=None),
        ]
    )
    raw_opa = pl.LazyFrame(
        {
            "parcel_number": ["888080493", "888080358", "888051001", "888051002", "123456789"],
            "location": [
                "1420 LOCUST ST",
                "1420  LOCUST ST",  # double space normalizes
                "200 LOCUST ST",
                "200 LOCUST ST",  # duplicate (base, unit) key -> ambiguous
                "108 ELFRETHS ALY",
            ],
            "unit": ["33K", "8L", "5A", "5A", None],
        }
    )
    out = stg_deeds(raw, raw_opa).collect()
    by_id = {row["record_id"]: row for row in out.to_dicts()}
    assert by_id["c1"]["opa_account_num"] == "888080493"
    assert by_id["c1"]["has_opa_link"] is True
    assert by_id["c1"]["opa_link_source"] == "address_unit"
    assert by_id["c2"]["opa_account_num"] == "888080358"
    assert by_id["c3"]["opa_account_num"] is None
    assert by_id["c3"]["opa_link_source"] is None
    assert by_id["c4"]["opa_account_num"] == "123456789"
    assert by_id["c4"]["opa_link_source"] == "rtt"
    assert by_id["c5"]["opa_account_num"] is None


def test_stg_opa_properties_adds_parsed_columns():
    raw = pl.LazyFrame(
        {
            "parcel_number": ["1"],
            "assessment_date": ["2026-04-29T15:45:08Z"],
            "market_value_date": [None],
            "sale_date": ["206-04-22T04:56:02Z"],
            "recording_date": ["2023-01-01T00:00:00Z"],
            "date_exterior_condition": [None],
            "year_built": ["1750"],
            "house_number": ["108"],
            # real point sampled from opa_properties_public (lon ~ -75.03, lat ~ 40.04)
            "the_geom": ["0101000020E6100000AAFF97D2E0C152C045882B37A2054440"],
        }
    )
    out = stg_opa_properties(raw).collect()
    assert out["assessment_date_status"].to_list() == ["ok"]
    assert out["sale_date_status"].to_list() == ["implausible"]
    assert out["year_built_parsed"].to_list() == [1750]
    assert out["house_number_parsed"].to_list() == [108]
    assert out["lonlat_status"].to_list() == ["ok"]
    assert abs(out["lon"][0] - -75.0293) < 0.001
    assert abs(out["lat"][0] - 40.0440) < 0.001
    # raw passthrough intact
    assert out["parcel_number"].to_list() == ["1"]
