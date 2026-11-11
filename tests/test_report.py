from datetime import datetime

import polars as pl

from philly_fair_measure.report import ReportData, render_html


def _screen_row(**overrides):
    row = {
        "parcel_id": "052174500",
        "address": "108 ELFRETHS ALY",
        "char_category": "SINGLE FAMILY",
        "opa_market_value": 441_900.0,
        "model_median": 520_000.0,
        "model_pi_low_90": 150_000.0,
        "model_pi_high_90": 1_800_000.0,
        "opa_vs_model_ratio": 0.85,
        "screen_z": -0.4,
        "assessment_flag": "within_range",
        "interval_method": "bayesian_posterior",
        "model_family": "residential",
        "twin_n": 6,
        "opa_vs_twin_median": 1.43,
        "aerial_change_score": 0.91,
        "aerial_change_flag": True,
        "aerial_pair": "2023_vs_2025",
        "evt_n_vacant_complaints_5y_before": 2.0,
        "evt_vacant_complaint_days_since": 400.0,
        "evt_n_unpermitted_work_complaints_5y_before": 1.0,
        "dist_tax_delinquent": 0.0,
        "ten_rental_license_at_sale": 1.0,
        "shp_n_linked_parcels": 1.0,
        "char_livable_area": 1120.0,
        "char_year_built": 1755.0,
        "char_interior_condition": "4",
    }
    row.update(overrides)
    return row


def test_render_html_full_packet():
    data = ReportData(
        parcel_id="052174500",
        screen=_screen_row(),
        characteristics={
            "char_livable_area": 1120.0,
            "char_lot_area": 700.0,
            "char_style": "row",
            "char_stories": 2.0,
            "char_year_built": 1755.0,
            "char_beds": 3.0,
            "char_baths": 1.0,
            "char_exterior_condition": "4",
            "char_interior_condition": "4",
            "char_quality_grade_raw": "C",
            "loc_lon": -75.1425,
            "loc_lat": 39.9527,
        },
        comps=pl.DataFrame(
            [
                {
                    "address": "109 ELFRETHS ALY",
                    "sale_date": datetime(2024, 5, 1),
                    "sale_price": 500_000.0,
                    "price_adj_today": 520_000.0,
                    "char_livable_area": 1100.0,
                    "char_style": "row",
                    "distance_m": 26.0,
                }
            ]
        ),
        twins=pl.DataFrame(
            [
                {
                    "parcel_id": "052174500",
                    "address": "108 ELFRETHS ALY",
                    "opa_market_value": 441_900.0,
                },
                {
                    "parcel_id": "052174501",
                    "address": "110 ELFRETHS ALY",
                    "opa_market_value": 310_000.0,
                },
            ]
        ),
        assessment_history=pl.DataFrame(
            {"year": [2015, 2020, 2026], "market_value": [200_000.0, 300_000.0, 441_900.0]}
        ),
        sale_history=pl.DataFrame(
            [
                {
                    "sale_date": datetime(2023, 4, 1),
                    "sale_price": 405_000.0,
                    "deed_kind": "standard",
                    "validity_status": "arms_length",
                }
            ]
        ),
        provenance={"screen_built": "2026-07-03", "generated": "2026-07-03"},
    )
    out = render_html(data)
    assert "<html>" in out and "</html>" in out
    # deep-link section: pointers to public viewers, no scraped imagery
    assert "atlas.phila.gov/108%20ELFRETHS%20ALY" in out
    assert "property.phila.gov/?p=052174500" in out
    assert "map_action=pano" in out
    for needle in (
        "108 ELFRETHS ALY",
        "View this property",
        "Uniformity exhibit",
        "identical in every",
        "Comparable arms-length sales",
        "Aerial change",
        "Vacancy complaints",
        "Unpermitted-work complaints",
        "Assessment history",
        "$441,900",
        "not legal or appraisal advice",
        "(this property)",
    ):
        assert needle in out, needle
    # svg sparkline rendered
    assert "<svg" in out and "polyline" in out


def test_render_html_includes_driver_panel():
    from philly_fair_measure.models.explain import Driver, Explanation

    exp = Explanation(
        value=520_000.0,
        base_value=249_000.0,
        drivers=[
            Driver(
                "char_livable_area", "living area", "Home characteristics", 1120.0, 0.15, 78_000.0
            ),
            Driver(
                "mkt_block_roll_mean_price",
                "recent sale prices on your block",
                "Recent nearby sales",
                None,
                -0.08,
                -40_000.0,
            ),
        ],
    )
    data = ReportData(
        parcel_id="052174500",
        screen=_screen_row(),
        characteristics={},
        explanation=exp,
        provenance={"generated": "2026-07-03"},
    )
    out = render_html(data)
    assert "What's driving this estimate" in out
    assert "typical home (about $249,000)" in out
    assert "Home characteristics" in out and "+$78,000" in out  # category view
    assert "Living area (1,120 sq ft) adds about $78,000." in out  # plain-language driver
    assert "not whether the assessment is fair" in out  # honesty caveat kept


def test_render_html_includes_appeal_panel():
    from philly_fair_measure.models.explain import Driver, Explanation

    exp = Explanation(
        value=200_000.0,
        base_value=249_000.0,
        drivers=[
            Driver(
                "char_livable_area", "living area", "Home characteristics", 420.0, -0.4, -80_000.0
            ),
        ],
    )
    data = ReportData(
        parcel_id="052174500",
        screen=_screen_row(),
        characteristics={"char_livable_area": 420.0},
        explanation=exp,
        provenance={"generated": "2026-07-03"},
    )
    out = render_html(data)
    assert "Facts to check" in out
    assert "living area ⚠" in out  # implausible flag rendered
    assert "documentable correction" in out


def test_render_html_includes_equity_panel():
    from philly_fair_measure.equity_context import EquityContext

    ctx = EquityContext(
        ratio=1.18,
        peer_median_ratio=0.95,
        peer_n=1240,
        percentile=88.0,
        peer_label="ZIP 19146, similar value",
        verdict="over",
    )
    data = ReportData(
        parcel_id="052174500",
        screen=_screen_row(),
        characteristics={},
        equity=ctx,
        provenance={"generated": "2026-07-03"},
    )
    out = render_html(data)
    assert "How your assessment compares" in out
    assert "118% of estimated market value" in out
    assert "95% (median of 1,240; ZIP 19146, similar value)" in out
    assert "assessed above 88% of them" in out
    assert "possible over-assessment" in out  # over verdict
    assert "does not prove the assessment unfair" in out  # honesty caveat


def test_leaderboards_rank_by_confidence_and_uniformity(tmp_path):
    from philly_fair_measure.ingest.derived import write_derived_table
    from philly_fair_measure.ingest.manifests import InputRef
    from philly_fair_measure.report import leaderboards

    def row(pid, addr, opa, model, ratio, z, pi_lo, pi_hi, flag, twin_n=6, twin_med=1.0):
        return {
            "parcel_id": pid,
            "address": addr,
            "opa_market_value": opa,
            "model_median": model,
            "opa_vs_model_ratio": ratio,
            "screen_z": z,
            "model_pi_low_90": pi_lo,
            "model_pi_high_90": pi_hi,
            "assessment_flag": flag,
            "twin_n": twin_n,
            "opa_vs_twin_median": twin_med,
        }

    rows = [
        row(
            f"w{i}",
            f"{i} MAIN ST",
            200_000.0,
            200_000.0,
            1.0,
            0.0,
            180_000.0,
            220_000.0,
            "within_range",
        )
        for i in range(15)
    ]
    rows += [
        # over-assessed, tight intervals: ranked by screen_z, not ratio
        row(
            "over_confident",
            "1 HIGH ST",
            300_000.0,
            100_000.0,
            3.0,
            5.0,
            80_000.0,
            130_000.0,
            "over_assessed_candidate",
        ),
        row(
            "over_modest",
            "2 HIGH ST",
            180_000.0,
            120_000.0,
            1.5,
            2.0,
            100_000.0,
            150_000.0,
            "over_assessed_candidate",
        ),
        # biggest ratio but a 20x interval -> the model can't value it (blind spot)
        row(
            "over_blindspot",
            "9 HUGE ST",
            700_000.0,
            50_000.0,
            14.0,
            2.5,
            20_000.0,
            400_000.0,
            "over_assessed_candidate",
        ),
        row(
            "under_x",
            "1 LOW ST",
            100_000.0,
            300_000.0,
            0.33,
            -4.0,
            250_000.0,
            380_000.0,
            "under_assessed_candidate",
        ),
        row(
            "odd_twin",
            "9 SAME ST",
            350_000.0,
            200_000.0,
            1.75,
            1.0,
            180_000.0,
            240_000.0,
            "within_range",
            twin_n=8,
            twin_med=1.5,
        ),
    ]
    write_derived_table(
        pl.DataFrame(rows),
        tmp_path,
        "marts",
        "assessment_screen",
        [InputRef(dataset="t", fetched_at="t")],
    )
    boards = leaderboards(tmp_path, n=5)  # default: interval-width filter + screen_z rank

    over = boards["over_assessed"]["parcel_id"].to_list()
    assert over[0] == "over_confident"  # highest screen_z, not highest ratio
    assert "over_blindspot" not in over  # 20x interval -> filtered as a blind spot
    assert boards["under_assessed"]["parcel_id"][0] == "under_x"  # most negative screen_z
    assert boards["non_uniform_block"]["parcel_id"][0] == "odd_twin"  # biggest twin gap

    extremes = leaderboards(tmp_path, n=5, plausible=False)
    assert extremes["over_assessed"]["parcel_id"][0] == "over_blindspot"  # raw biggest ratio


def test_render_html_minimal_condo():
    data = ReportData(
        parcel_id="888080493",
        screen=_screen_row(
            parcel_id="888080493",
            address="1420 LOCUST ST #16C",
            model_family="condo",
            interval_method="conformal_knn",
            twin_n=None,
            opa_vs_twin_median=None,
            aerial_change_score=None,
            bldg_n_units=270,
            evt_n_vacant_complaints_5y_before=0.0,
            evt_n_unpermitted_work_complaints_5y_before=0.0,
            ten_rental_license_at_sale=0.0,
            shp_n_linked_parcels=None,
        ),
        characteristics={},
        provenance={"generated": "2026-07-03"},
    )
    out = render_html(data)
    assert "1420 LOCUST ST #16C" in out
    assert "conformal" in out
    assert "270 units" in out
    assert "Uniformity exhibit" not in out  # no twins for condos yet
