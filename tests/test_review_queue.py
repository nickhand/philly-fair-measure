from __future__ import annotations

import polars as pl
import pytest

from philly_fair_measure.diagnostics.review_queue import build_review_queue_frame


def _screen() -> pl.DataFrame:
    rows = []
    for i in range(20):
        rows.append(
            {
                "parcel_id": f"p{i}",
                "address": f"{i} TEST ST",
                "model_family": "residential",
                "loc_district": "north" if i < 10 else "south",
                "display_median": 100_000.0 + i * 50_000.0,
                "display_pi_low_90": 70_000.0 + i * 40_000.0,
                "display_pi_high_90": 150_000.0 + i * 70_000.0,
                "opa_market_value": 125_000.0 + i * 55_000.0,
                "assessment_flag": "within_range",
                "prediction_risk_score": 0.1 + i / 100.0,
                "prediction_risk_tier": "high" if i % 3 == 0 else "elevated",
                "quality_zero_bed_bath_conflict": i % 2 == 0,
                "quality_area_outlier": False,
                "quality_characteristic_outlier": i % 4 == 0,
                "quality_characteristic_conflict_score": i / 10.0,
                "state_active_work_evidence": 0.8 if i % 5 == 0 else 0.0,
                "state_distress_evidence": 0.7 if i % 3 == 0 else 0.0,
                "state_competing_evidence": 0.3 if i % 7 == 0 else 0.0,
                "state_transition_evidence": 0.8 if i % 5 == 0 else 0.0,
                "char_livable_area": 1_200.0,
                "char_beds": 0 if i % 2 == 0 else 3,
                "char_baths": 0 if i % 2 == 0 else 1,
                "quality_expected_livable_area": 1_300.0,
                "quality_area_reference_low_90": 900.0,
                "quality_area_reference_high_90": 1_600.0,
                "quality_expected_beds": 3.0,
                "quality_expected_baths": 1.5,
                "state_primary_evidence": "distressed" if i % 3 == 0 else "stable_or_unknown",
            }
        )
    return pl.DataFrame(rows)


def test_review_queue_is_limited_and_stratified():
    queue = build_review_queue_frame(_screen(), limit=10)
    assert queue.height == 10
    assert queue["review_reasons"].list.len().min() > 0
    assert queue["review_priority"].min() > 0
    assert queue["review_priority"].is_finite().all()
    # Rank-first ordering gives broad stratum coverage before taking seconds.
    assert queue["review_stratum"].n_unique() >= 6
    assert queue["review_rank_within_stratum"].max() <= 2
    assert set(queue["loc_district"].to_list()) == {"north", "south"}


def test_review_queue_rejects_nonpositive_limit():
    with pytest.raises(ValueError, match="positive"):
        build_review_queue_frame(_screen(), limit=0)
