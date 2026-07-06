import math
from datetime import datetime

import polars as pl
import pytest

from philly_fair_measure.features.sale_features import assemble_sale_features


def _sale(sale_id, parcel, price, date, status="arms_length"):
    return {
        "sale_id": sale_id,
        "parcel_id": parcel,
        "sale_date": date,
        "sale_price": price,
        "sale_year": date.year,
        "zip5": "19106",
        "category_code_description": "SINGLE FAMILY",
        "validity_status": status,
    }


def _opa(parcel, street="12345", house_number=101):
    return {
        "parcel_number": parcel,
        "street_code": street,
        "house_number_parsed": house_number,
        "census_tract": "001",
        "geographic_ward": "05",
        "lon": -75.14,
        "lat": 39.95,
        "lonlat_status": "ok",
        "total_livable_area": 1200.0,
        "total_area": 900.0,
        "frontage": 16.0,
        "depth": 60.0,
        "number_of_bedrooms": 3,
        "number_of_bathrooms": 1,
        "number_of_rooms": 6,
        "number_stories": 2,
        "year_built_parsed": 1920,
        "exterior_condition": "4",
        "interior_condition": "4",
        "quality_grade": "C",
        "basements": "D",
        "central_air": "N",
        "garage_spaces": 0,
        "fireplaces": 0,
        "type_heater": "H",
        "general_construction": "A",
        "view_type": "I",
        "topography": "F",
        "zoning": "RSA5",
        "building_code_description_new": "ROW PORCH FRONT",
    }


def _weight(days):
    return 1.0 / (1.0 + math.exp(days / 365.25 - 3.0))


def _assemble(sales, opa, permits=None, violations=None, assessments=None, **kwargs):
    permits = permits or [
        {"opa_account_num": "zzz", "permitissuedate_parsed": datetime(2019, 1, 1)}
    ]
    violations = violations or [
        {
            "opa_account_num": "zzz",
            "violationdate_parsed": datetime(2019, 1, 1),
            "violationresolutiondate_parsed": None,
            "caseprioritydesc": "STANDARD",
        }
    ]
    violations = [{"caseprioritydesc": "STANDARD", **v} for v in violations]
    assessments = assessments or [
        {"parcel_number": "zzz", "year_parsed": 2020, "market_value": 1.0}
    ]
    out = assemble_sale_features(
        pl.LazyFrame(sales),
        pl.LazyFrame(opa),
        pl.LazyFrame(permits),
        pl.LazyFrame(violations),
        pl.LazyFrame(assessments),
        **kwargs,
    )
    return {row["sale_id"]: row for row in out.to_dicts()}


def test_block_roll_ppsf_null_when_no_peer_has_valid_area():
    # peer sale exists but its parcel has an implausible livable area:
    # the $/sqft roll must be null (not NaN from 0/0), price roll still works
    sales = [
        _sale("first", "p1", 200_000.0, datetime(2020, 1, 1)),
        _sale("target", "p2", 300_000.0, datetime(2021, 1, 1)),
    ]
    opa = [
        _opa("p1", house_number=101) | {"total_livable_area": 50.0},  # < plausible bound
        _opa("p2", house_number=103),
    ]
    by_id = _assemble(sales, opa)
    row = by_id["target"]
    assert row["mkt_block_roll_mean_price"] == pytest.approx(200_000.0)
    assert row["mkt_block_roll_ppsf"] is None


def test_block_rolling_mean_and_parcel_priors():
    sales = [
        _sale("a", "p1", 100_000.0, datetime(2020, 1, 1)),
        _sale("b", "p2", 200_000.0, datetime(2021, 1, 1)),
        _sale("d_prev", "p3", 250_000.0, datetime(2022, 1, 1)),
        _sale("c", "p3", 300_000.0, datetime(2023, 6, 1)),
        # suspect sale on the same block must not feed anyone's rolling mean
        _sale("bad", "p4", 900_000.0, datetime(2022, 6, 1), status="suspect"),
    ]
    opa = [
        _opa("p1", house_number=101),
        _opa("p2", house_number=103),
        _opa("p3", house_number=105),
        _opa("p4", house_number=107),
    ]
    by_id = _assemble(sales, opa)
    assert "bad" not in by_id

    # sale c: block peers are a and b (d_prev is the same parcel -> excluded)
    days_b = (datetime(2023, 6, 1) - datetime(2021, 1, 1)).days
    days_a = (datetime(2023, 6, 1) - datetime(2020, 1, 1)).days
    w_a, w_b = _weight(days_a), _weight(days_b)
    expected = (w_a * 100_000 + w_b * 200_000) / (w_a + w_b)
    assert by_id["c"]["mkt_block_roll_n"] == 2
    assert by_id["c"]["mkt_block_roll_mean_price"] == pytest.approx(expected)

    # earliest sale has no priors
    assert by_id["a"]["mkt_block_roll_n"] == 0
    assert by_id["a"]["mkt_block_roll_mean_price"] is None

    # parcel-level repeat sale features for c (prior sale of p3 in 2022)
    assert by_id["c"]["mkt_parcel_n_prior_sales"] == 1
    assert by_id["c"]["mkt_parcel_prev_price"] == 250_000.0
    assert by_id["c"]["mkt_parcel_days_since_prev"] == 516

    # characteristics and location renames landed
    assert by_id["c"]["char_livable_area"] == 1200.0
    assert by_id["c"]["loc_block_id"] == "12345_100"
    assert by_id["c"]["loc_ward"] == "05"


def test_event_features_do_not_leak_the_future():
    sales = [_sale("s", "p1", 200_000.0, datetime(2020, 1, 1))]
    permits = [
        {"opa_account_num": "p1", "permitissuedate_parsed": datetime(2019, 6, 1)},  # counts
        {"opa_account_num": "p1", "permitissuedate_parsed": datetime(2020, 6, 1)},  # future!
        {"opa_account_num": "p1", "permitissuedate_parsed": datetime(2013, 1, 1)},  # > 5y ago
    ]
    violations = [
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2019, 1, 1),
            "violationresolutiondate_parsed": datetime(2019, 6, 1),  # resolved before sale
        },
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2019, 12, 1),
            "violationresolutiondate_parsed": None,  # still open at sale
        },
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2021, 1, 1),  # future!
            "violationresolutiondate_parsed": None,
        },
    ]
    by_id = _assemble(sales, [_opa("p1")], permits=permits, violations=violations)
    row = by_id["s"]
    assert row["evt_n_permits_5y_before"] == 1
    assert row["evt_days_since_last_permit"] == 214
    assert row["evt_n_violations_5y_before"] == 2
    assert row["evt_n_open_violations_at_sale"] == 1


def test_condo_accounts_excluded_from_scope_and_pools():
    # an 88-prefix (condo) sale on the block must neither appear in the output
    # nor feed the block rolling average of its neighbors
    sales = [
        _sale("condo", "880001111", 500_000.0, datetime(2020, 1, 1)),
        _sale("house", "p1", 300_000.0, datetime(2021, 1, 1)),
    ]
    opa = [_opa("880001111", house_number=101), _opa("p1", house_number=103)]
    by_id = _assemble(sales, opa)
    assert "condo" not in by_id
    assert by_id["house"]["mkt_block_roll_n"] == 0


def test_distress_features_severity_demo_delinquency():
    from philly_fair_measure.features.sale_features import assemble_sale_features

    sales = [_sale("s", "p1", 80_000.0, datetime(2020, 6, 1))]
    violations = [
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2019, 1, 1),
            "violationresolutiondate_parsed": None,
            "caseprioritydesc": "UNSAFE",  # severe, open at sale
        },
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2019, 6, 1),
            "violationresolutiondate_parsed": datetime(2019, 8, 1),
            "caseprioritydesc": "STANDARD",  # not severe
        },
    ]
    demolitions = pl.LazyFrame(
        [
            {  # before the sale: counts
                "opa_account_num": "p1",
                "completed_date_parsed": datetime(2018, 6, 1),
                "start_date_parsed": datetime(2018, 5, 1),
            },
            {  # after the sale: leakage guard
                "opa_account_num": "p1",
                "completed_date_parsed": datetime(2021, 6, 1),
                "start_date_parsed": None,
            },
        ]
    )
    delinquencies = pl.LazyFrame(
        [
            {
                "opa_account_num": "p1",
                "num_years_owed": 3,
                "total_due": 4_200.0,
                "sheriff_sale": "Y",
            }
        ]
    )
    out = assemble_sale_features(
        pl.LazyFrame(sales),
        pl.LazyFrame([_opa("p1")]),
        pl.LazyFrame([{"opa_account_num": "zz", "permitissuedate_parsed": datetime(2019, 1, 1)}]),
        pl.LazyFrame(violations),
        pl.LazyFrame([{"parcel_number": "zz", "year_parsed": 2020, "market_value": 1.0}]),
        demolitions=demolitions,
        delinquencies=delinquencies,
    )
    row = out.to_dicts()[0]
    assert row["evt_n_severe_violations_5y_before"] == 1
    assert row["evt_n_open_severe_at_sale"] == 1
    assert row["evt_n_violations_5y_before"] == 2
    assert row["evt_n_demolitions_before"] == 1  # future demolition excluded
    assert row["evt_demo_days_since"] == (datetime(2020, 6, 1) - datetime(2018, 6, 1)).days
    assert row["dist_tax_delinquent"] == 1.0
    assert row["dist_tax_years_owed"] == 3.0
    assert row["dist_sheriff_sale"] == 1.0


def test_assessment_join_and_population_window():
    sales = [
        _sale("old", "p1", 90_000.0, datetime(2014, 3, 1)),  # pool-only: before min year
        _sale("new", "p2", 250_000.0, datetime(2016, 3, 1)),
    ]
    opa = [_opa("p1", house_number=101), _opa("p2", house_number=103)]
    assessments = [
        {"parcel_number": "p2", "year_parsed": 2016, "market_value": 180_000.0},
        {"parcel_number": "p2", "year_parsed": 2015, "market_value": 150_000.0},
    ]
    by_id = _assemble(sales, opa, assessments=assessments, min_sale_year=2016)

    assert "old" not in by_id  # filtered from output...
    row = by_id["new"]
    assert row["mkt_block_roll_n"] == 1  # ...but still feeds the rolling window
    assert row["mkt_block_roll_mean_price"] == pytest.approx(90_000.0)

    assert row["asmt_market_value_sale_year"] == 180_000.0
    assert row["asmt_value_yoy_change"] == pytest.approx(0.2)
