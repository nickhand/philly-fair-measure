"""Release-day annual roll report: direction, warnings, and stable tiers."""

from datetime import datetime

import polars as pl

from philly_fair_measure.diagnostics.annual_roll import (
    AnnualRollConfig,
    build_annual_roll_report,
)


def _frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    parcels = [f"p{i:02d}" for i in range(1, 11)]
    old = [80, 85, 90, 95, 100, 105, 110, 115, 120, 125]
    # First five move toward their model estimate; next four move away; the
    # last is a known data warning and must not enter the direction verdict.
    new = [90, 95, 100, 105, 110, 115, 120, 125, 130, 135]
    model = [100, 105, 110, 115, 120, 95, 100, 105, 110, 145]
    assessments = pl.DataFrame(
        {
            "parcel_number": parcels + parcels,
            "year_parsed": [2026] * 10 + [2027] * 10,
            "market_value": old + new,
        }
    )
    screen = pl.DataFrame(
        {
            "parcel_id": parcels + ["commercial"],
            "model_family": ["residential"] * 10 + ["commercial"],
            "loc_zip5": ["19134"] * 5 + ["19125"] * 5 + ["19102"],
            "opa_market_value": new + [999],
            "display_median": model + [999],
            "display_pi_low_90": [v * 0.9 for v in model] + [900],
            "display_pi_high_90": [v * 1.1 for v in model] + [1_100],
            "record_quality_warning": [False] * 9 + [True, False],
            "valuation_date": [datetime(2026, 7, 14)] * 11,
        }
    )
    # Five points step west from the 19125-side proxy into 19134. At
    # Philadelphia's latitude these span roughly 0.25 km to 3 km.
    locations = pl.DataFrame(
        {
            "parcel_id": parcels,
            "loc_lon": [
                -75.133,
                -75.137,
                -75.142,
                -75.150,
                -75.165,
                -75.130,
                -75.130,
                -75.130,
                -75.130,
                -75.130,
            ],
            "loc_lat": [39.98] * 10,
        }
    )
    return assessments, screen, locations


def test_annual_roll_report_keeps_warning_out_of_direction_verdict() -> None:
    assessments, screen, _ = _frames()
    report = build_annual_roll_report(
        assessments,
        screen,
        AnnualRollConfig(
            tax_year=2027,
            comparison_year=2026,
            effective_date="2027-01-01",
            sales_cutoff="2025-06-30",
            min_log_direction=0.02,
            min_area_n=2,
        ),
    )

    assert report["n_properties"] == 10
    assert report["benchmark_date"] == "2026-07-14"
    assert report["correction"]["n_reliable"] == 9
    assert report["correction"]["n_data_warning"] == 1
    assert report["correction"]["corrective_pct"] > 0
    assert report["correction"]["widening_pct"] > 0
    assert set(report["vertical_equity"]) >= {"prd", "prb", "vei", "basis"}
    assert set(report["vertical_equity"]["metric_directions"]) == {"prd", "prb", "vei"}
    assert report["vertical_equity"]["standard_metrics_verdict"] in {
        "improved",
        "worsened",
        "unchanged",
        "mixed",
    }
    assert set(report["vertical_equity"]["tier_movement"]) == {
        "cheapest",
        "most_expensive",
        "larger_shift",
    }
    assert set(report["uniformity"]) == {"old_cod", "new_cod", "verdict"}
    assert len(report["tiers"]) == 5
    assert report["tiers"][0]["label"] == "Cheapest 20%"
    assert report["tiers"][-1]["label"] == "Most expensive 20%"
    assert {area["zip"] for area in report["areas"]} == {"19125", "19134"}
    assert report["areas"] == sorted(
        report["areas"], key=lambda area: (-area["median_change_pct"], area["zip"])
    )


def test_annual_roll_report_requires_both_named_rolls() -> None:
    assessments, screen, _ = _frames()
    assessments = assessments.filter(pl.col("year_parsed") == 2027)

    try:
        build_annual_roll_report(
            assessments,
            screen,
            AnnualRollConfig(
                tax_year=2027,
                comparison_year=2026,
                effective_date="2027-01-01",
                sales_cutoff="2025-06-30",
            ),
        )
    except ValueError as exc:
        assert "must contain 2026 and 2027" in str(exc)
    else:
        raise AssertionError("missing comparison roll should fail")


def test_annual_roll_report_builds_reproducible_boundary_bands() -> None:
    assessments, screen, locations = _frames()
    report = build_annual_roll_report(
        assessments,
        screen,
        AnnualRollConfig(
            tax_year=2027,
            comparison_year=2026,
            effective_date="2027-01-01",
            sales_cutoff="2025-06-30",
            min_log_direction=0.02,
            min_area_n=2,
        ),
        locations=locations,
    )

    transect = report["boundary_transect"]
    assert transect["core_zips"] == ["19122", "19125"]
    assert transect["corridor_zips"] == ["19133", "19134", "19140", "19124"]
    assert transect["n_core"] == 4  # one core record carries a quality warning
    assert transect["n_corridor"] == 5
    assert transect["bands"][0]["label"] == "0–0.5 km"
    assert transect["bands"][-1]["label"] == "2.5+ km"
    assert sum(row["n"] for row in transect["bands"]) == transect["n_corridor"]


def test_annual_roll_report_summarizes_race_as_neighborhood_context() -> None:
    assessments, screen, _ = _frames()
    demographics = pl.DataFrame(
        {
            "parcel_id": [f"p{i:02d}" for i in range(1, 11)],
            "acs_majority_race": (
                ["White alone"] * 3
                + ["Black alone"] * 3
                + ["Hispanic/Latino, any race"] * 3
                + ["No Majority"]
            ),
        }
    )
    report = build_annual_roll_report(
        assessments,
        screen,
        AnnualRollConfig(
            tax_year=2027,
            comparison_year=2026,
            effective_date="2027-01-01",
            sales_cutoff="2025-06-30",
            min_area_n=2,
        ),
        demographics=demographics,
    )

    rows = report["race_context"]
    assert [row["label"] for row in rows] == [
        "Majority-White tracts",
        "Majority-Black tracts",
        "Majority-Hispanic tracts",
    ]
    assert all(row["n"] == 3 for row in rows)
    assert all(set(row) >= {"old_ratio_pct", "new_ratio_pct", "corrective_pct"} for row in rows)
