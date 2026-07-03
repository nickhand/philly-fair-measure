import math
from datetime import datetime

import polars as pl
import pytest

from philly_assessments.features.assessment_features import assemble_assessment_features
from philly_assessments.features.sale_features import _CHAR_RENAMES, _LOC_RENAMES
from philly_assessments.validation.opa import finalize_screen

VALUATION_DATE = datetime(2026, 7, 1)


def _opa_row(parcel, street="12345", house_number=101, market_value=250_000.0):
    row = {
        "parcel_number": parcel,
        "location": f"{house_number} TEST ST",
        "market_value": market_value,
        "zip_code": "19106",
        "category_code_description": "SINGLE FAMILY",
        "street_code": street,
        "house_number_parsed": house_number,
    }
    for source in _CHAR_RENAMES:
        row.setdefault(source, None)
    for source in _LOC_RENAMES:
        row.setdefault(source, None)
    row["total_livable_area"] = 1200.0
    return row


def _sale(parcel, price, date, status="arms_length"):
    return {
        "parcel_id": parcel,
        "sale_price": price,
        "sale_date": date,
        "validity_status": status,
    }


def _weight(days):
    return 1.0 / (1.0 + math.exp(days / 365.25 - 3.0))


def _assemble(opa_rows, sale_rows, permits=None, violations=None):
    permits = permits or [
        {"opa_account_num": "zz", "permitissuedate_parsed": datetime(2020, 1, 1)}
    ]
    violations = violations or [
        {
            "opa_account_num": "zz",
            "violationdate_parsed": datetime(2020, 1, 1),
            "violationresolutiondate_parsed": None,
            "caseprioritydesc": "STANDARD",
        }
    ]
    violations = [{"caseprioritydesc": "STANDARD", **v} for v in violations]
    out = assemble_assessment_features(
        pl.LazyFrame(opa_rows),
        pl.LazyFrame(sale_rows),
        pl.LazyFrame(permits),
        pl.LazyFrame(violations),
        VALUATION_DATE,
    )
    return {row["parcel_id"]: row for row in out.to_dicts()}


def test_block_roll_excludes_own_sales_at_valuation_date():
    opa = [_opa_row("p1", house_number=101), _opa_row("p2", house_number=103),
           _opa_row("p3", house_number=105)]
    sales = [
        _sale("p1", 200_000.0, datetime(2025, 7, 1)),   # 365d before valuation
        _sale("p2", 300_000.0, datetime(2024, 7, 1)),   # 730d before
        _sale("p2", 900_000.0, datetime(2024, 8, 1), status="suspect"),  # never counts
        _sale("p1", 111_000.0, datetime(2019, 1, 1)),   # outside 5y window
    ]
    by_id = _assemble(opa, sales)

    w1, w2 = _weight(365), _weight(730)
    # p3 never sold: sees both neighbors
    assert by_id["p3"]["mkt_block_roll_n"] == 2
    assert by_id["p3"]["mkt_block_roll_mean_price"] == pytest.approx(
        (w1 * 200_000 + w2 * 300_000) / (w1 + w2)
    )
    # p1 must not see its own sale
    assert by_id["p1"]["mkt_block_roll_n"] == 1
    assert by_id["p1"]["mkt_block_roll_mean_price"] == pytest.approx(300_000.0)
    # prior-sale features come from the parcel's own history (both sales, latest last)
    assert by_id["p1"]["mkt_parcel_n_prior_sales"] == 2
    assert by_id["p1"]["mkt_parcel_prev_price"] == 200_000.0
    assert by_id["p1"]["mkt_parcel_days_since_prev"] == 365
    # time features are valuation-date constants
    assert by_id["p2"]["time_quarter"] == 3
    expected_epoch = float((VALUATION_DATE - datetime(1997, 1, 1)).days)
    assert by_id["p2"]["time_sale_epoch_days"] == expected_epoch


def test_event_windows_anchor_on_valuation_date():
    opa = [_opa_row("p1")]
    permits = [
        {"opa_account_num": "p1", "permitissuedate_parsed": datetime(2026, 1, 1)},  # counts
        {"opa_account_num": "p1", "permitissuedate_parsed": datetime(2026, 8, 1)},  # future
    ]
    violations = [
        {
            "opa_account_num": "p1",
            "violationdate_parsed": datetime(2025, 1, 1),
            "violationresolutiondate_parsed": None,  # open at valuation
        },
    ]
    by_id = _assemble(opa, [_sale("zz", 1.0, datetime(2020, 1, 1))], permits, violations)
    row = by_id["p1"]
    assert row["evt_n_permits_5y_before"] == 1
    assert row["evt_days_since_last_permit"] == 181
    assert row["evt_n_open_violations_at_sale"] == 1


def test_twin_uniformity_strict_key():
    from philly_assessments.validation.opa import twin_uniformity

    def _parcel(pid, value, area=1000.0, cond="4"):
        return {
            "parcel_id": pid, "opa_market_value": value, "loc_block_id": "b1",
            "char_livable_area": area, "char_lot_area": 800.0, "char_style": "row",
            "char_stories": 2.0, "char_year_built": 1925.0,
            "char_exterior_condition": cond, "char_interior_condition": "4",
            "char_quality_grade_raw": "C", "char_basement": "D",
            "char_garage_spaces": 0.0, "char_central_air": "N",
        }

    rows = [_parcel(f"p{i}", 100_000.0) for i in range(5)]
    rows.append(_parcel("high", 150_000.0))          # identical but assessed 1.5x
    rows.append(_parcel("diff_cond", 150_000.0, cond="7"))  # condition differs -> own set
    rows.append(_parcel("diff_area", 100_000.0, area=1400.0))
    out = twin_uniformity(pl.DataFrame(rows))
    by = {r["parcel_id"]: r for r in out.to_dicts()}
    assert by["p0"]["twin_n"] == 6  # five equals + the outlier share the strict key
    assert by["p0"]["opa_vs_twin_median"] == pytest.approx(1.0)
    assert by["high"]["opa_vs_twin_median"] == pytest.approx(1.5)
    # different condition / area parcels fall out of the set (n < 5 -> excluded)
    assert "diff_cond" not in by and "diff_area" not in by


def test_finalize_screen_flags_and_ranking():
    df = pl.DataFrame(
        {
            "parcel_id": ["over", "under", "ok", "none"],
            "opa_market_value": [900_000.0, 100_000.0, 310_000.0, None],
            "pred_lightgbm_calibrated": [300_000.0, 300_000.0, 300_000.0, 300_000.0],
            "model_median": [300_000.0, 300_000.0, 300_000.0, 300_000.0],
            "model_pi_low_90": [150_000.0] * 4,
            "model_pi_high_90": [600_000.0] * 4,
        }
    )
    out = finalize_screen(df)
    flags = {row["parcel_id"]: row["assessment_flag"] for row in out.to_dicts()}
    assert flags == {
        "over": "over_assessed_candidate",
        "under": "under_assessed_candidate",
        "ok": "within_range",
        "none": "no_assessment",
    }
    by_id = {row["parcel_id"]: row for row in out.to_dicts()}
    assert by_id["over"]["screen_z"] > 0 and by_id["under"]["screen_z"] < 0
    assert by_id["over"]["opa_vs_model_ratio"] == pytest.approx(3.0)
    # ranked by |screen_z|, most confident disagreement first; nulls last
    assert out["parcel_id"].to_list()[-1] == "none"
    assert abs(out["screen_z"][0]) >= abs(out["screen_z"][1])
    # mixed model families finalize together (diagonal concat null-fills)
    mixed = pl.concat(
        [
            df.with_columns(pl.lit("residential").alias("model_family")),
            pl.DataFrame(
                {
                    "parcel_id": ["condo_over"],
                    "opa_market_value": [900_000.0],
                    "pred_lightgbm_calibrated": [300_000.0],
                    "model_median": [300_000.0],
                    "model_pi_low_90": [200_000.0],
                    "model_pi_high_90": [450_000.0],
                    "model_family": ["condo"],
                    "bldg_n_units": [42],
                }
            ),
        ],
        how="diagonal",
    )
    out2 = finalize_screen(mixed)
    row = out2.filter(pl.col("parcel_id") == "condo_over").to_dicts()[0]
    assert row["assessment_flag"] == "over_assessed_candidate"
    assert row["bldg_n_units"] == 42
    assert out2.filter(pl.col("model_family") == "residential")["bldg_n_units"].is_null().all()
