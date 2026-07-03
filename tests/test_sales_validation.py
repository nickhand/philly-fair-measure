from datetime import datetime

import polars as pl

from philly_assessments.validation.sales import classify_sales


def _deed(record_id, parcel, price, sale_date, **overrides):
    row = {
        "record_id": record_id,
        "opa_account_num": parcel,
        "has_opa_link": True,
        "zip_code": "19106",
        "sale_date": sale_date,
        "sale_price": price,
        "is_nominal": price is not None and price <= 1,
        "is_multi_parcel": False,
        "deed_kind": "standard",
        "grantors": "SELLER ALICE",
        "grantees": "BUYER BOB",
    }
    row.update(overrides)
    return row


def _opa(parcel, category="SINGLE FAMILY", area=1000.0):
    return {
        "parcel_number": parcel,
        "category_code_description": category,
        "total_livable_area": area,
    }


def _classify(deeds_rows, opa_rows):
    out = classify_sales(pl.LazyFrame(deeds_rows), pl.LazyFrame(opa_rows)).collect()
    return {row["sale_id"]: row for row in out.to_dicts()}


def test_rule_based_statuses():
    day = datetime(2023, 6, 1)
    deeds = [
        _deed("clean", "p1", 300_000.0, day),
        _deed("nominal", "p2", 1.0, day),
        _deed("sheriff", "p3", 150_000.0, day, deed_kind="sheriff"),
        _deed("landbank", "p4", 25_000.0, day, deed_kind="land_bank"),
        _deed("multi", "p5", 500_000.0, day, is_multi_parcel=True),
        _deed("nolink", "", 200_000.0, day, has_opa_link=False),
        _deed("nodate", "p6", 200_000.0, None),
        _deed("lowprice", "p7", 5_000.0, day),
        _deed("entity", "p8", 250_000.0, day, grantees="ACME HOLDINGS LLC"),
        _deed("related", "p9", 240_000.0, day, grantors="SMITH JOHN", grantees="SMITH MARY"),
    ]
    opa = [_opa(f"p{i}") for i in range(1, 10)]
    by_id = _classify(deeds, opa)

    assert by_id["clean"]["validity_status"] == "arms_length"
    assert by_id["clean"]["confidence"] == 0.9
    assert by_id["clean"]["validity_reasons"] == []

    assert by_id["nominal"]["validity_status"] == "nominal"
    assert "nominal_consideration" in by_id["nominal"]["validity_reasons"]

    assert by_id["sheriff"]["validity_status"] == "not_arms_length"
    assert "distress_deed" in by_id["sheriff"]["validity_reasons"]
    assert by_id["landbank"]["validity_status"] == "not_arms_length"

    assert by_id["multi"]["validity_status"] == "excluded"
    assert by_id["nolink"]["validity_status"] == "excluded"
    assert by_id["nodate"]["validity_status"] == "excluded"

    assert by_id["lowprice"]["validity_status"] == "suspect"
    assert "low_price" in by_id["lowprice"]["validity_reasons"]

    # name heuristics are supplementary: flags + lowered confidence, not status
    assert by_id["entity"]["validity_status"] == "arms_length"
    assert by_id["entity"]["non_person_buyer"] is True
    assert by_id["entity"]["confidence"] == 0.75
    assert "non_person_buyer" in by_id["entity"]["validity_reasons"]

    assert by_id["related"]["validity_status"] == "arms_length"
    assert by_id["related"]["possible_related"] is True
    assert "possible_related_parties" in by_id["related"]["validity_reasons"]


def test_resale_flags():
    deeds = [
        _deed("first", "p1", 100_000.0, datetime(2023, 1, 1)),
        _deed("flip", "p1", 260_000.0, datetime(2023, 6, 1)),
        _deed("dup_a", "p2", 150_000.0, datetime(2023, 1, 1)),
        _deed("dup_b", "p2", 150_000.0, datetime(2023, 3, 1)),
        _deed("slow", "p3", 100_000.0, datetime(2020, 1, 1)),
        _deed("slow_resale", "p3", 300_000.0, datetime(2023, 1, 1)),
    ]
    opa = [_opa("p1"), _opa("p2"), _opa("p3")]
    by_id = _classify(deeds, opa)

    assert by_id["first"]["validity_status"] == "arms_length"
    assert by_id["flip"]["validity_status"] == "suspect"
    assert "rapid_price_swing" in by_id["flip"]["validity_reasons"]
    assert by_id["flip"]["days_since_prev"] == 151

    assert by_id["dup_b"]["validity_status"] == "excluded"
    assert "dup_price_within_year" in by_id["dup_b"]["validity_reasons"]
    assert by_id["dup_a"]["validity_status"] == "arms_length"

    # a big price change over three years is fine
    assert by_id["slow_resale"]["validity_status"] == "arms_length"


def test_condo_units_pool_separately():
    day = datetime(2023, 3, 1)
    # 24 rowhome sales around $300k and 21 condo units around $900k in one zip;
    # the condo roll category is SINGLE FAMILY (as in the real roll), so
    # without the CONDO UNIT pool the condos would all z-score as outliers
    deeds = [_deed(f"h{i}", f"p{i}", 295_000.0 + 1_000.0 * i, day) for i in range(24)]
    deeds += [_deed(f"c{i}", f"88{i:07d}", 890_000.0 + 2_000.0 * i, day) for i in range(21)]
    opa = [_opa(f"p{i}") for i in range(24)]
    opa += [_opa(f"88{i:07d}", category="SINGLE FAMILY") for i in range(21)]
    by_id = _classify(deeds, opa)

    assert by_id["c5"]["pool_category"] == "CONDO UNIT"
    assert by_id["h5"]["pool_category"] == "SINGLE FAMILY"
    assert by_id["c5"]["group_n"] == 21  # condos compare against condos only
    assert by_id["h5"]["group_n"] == 24
    assert by_id["c5"]["validity_status"] == "arms_length"


def test_group_price_outlier():
    deeds = [
        _deed(f"normal{i}", f"g{i}", 280_000.0 + 5_000.0 * i, datetime(2023, 3, 1 + i))
        for i in range(24)
    ]
    deeds.append(_deed("crazy", "g99", 9_000_000.0, datetime(2023, 5, 1)))
    opa = [_opa(f"g{i}") for i in range(24)] + [_opa("g99")]
    by_id = _classify(deeds, opa)

    assert by_id["crazy"]["validity_status"] == "suspect"
    assert "price_outlier_high" in by_id["crazy"]["validity_reasons"]
    assert by_id["crazy"]["group_n"] == 25
    assert by_id["crazy"]["z_log_price"] > 3
    assert by_id["normal5"]["validity_status"] == "arms_length"
    assert by_id["normal5"]["in_reference_pool"] is True
