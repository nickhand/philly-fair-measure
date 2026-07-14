import polars as pl

from philly_fair_measure.diagnostics.characteristic_quality import evaluate_quality_segments
from philly_fair_measure.features.characteristic_quality import (
    QUALITY_COLUMNS,
    add_characteristic_quality,
    crossfit_characteristic_quality,
)


def _property_rows(n: int = 600) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(n):
        multifamily = i % 4 == 0
        floors = 3.0 if multifamily else 2.0
        footprint = float(450 + i % 120)
        gross = footprint * floors
        ratio = 0.82 + 0.04 * (i % 5)
        area = gross * ratio
        rows.append(
            {
                "parcel_id": f"p{i:04d}",
                "char_category": "MULTI FAMILY" if multifamily else "SINGLE FAMILY",
                "char_building_type": "ROW TYPICAL" if i % 2 else "ROW PORCH FRONT",
                "char_style": "row",
                "char_era": "prewar",
                "char_exterior_condition": "4",
                "char_interior_condition": "4",
                "loc_zip5": "19133" if i % 3 else "19122",
                "loc_ward": "05",
                "loc_lon": -75.15 + (i % 17) / 10_000,
                "loc_lat": 39.98 + (i % 19) / 10_000,
                "char_lot_area": 900.0 + i % 200,
                "char_frontage": 15.0 + i % 5,
                "char_depth": 60.0 + i % 10,
                "char_stories": floors,
                "char_year_built": 1920.0 + i % 20,
                "char_footprint_sqft": footprint,
                "char_footprint_estimated_floors": floors,
                "char_footprint_gross_sqft": gross,
                "char_footprint_story_gap": 0.0,
                "char_livable_area": area,
                "char_livable_to_footprint_gross_ratio": ratio,
                "char_area_conflict": 0.0,
                "char_beds": max(round(area / 500), 1),
                "char_baths": max(round(area / 900), 1),
                # These must never enter a characteristic model.
                "sale_price": float(50_000 + i * 10_000),
                "opa_market_value": float(900_000 - i * 500),
            }
        )
    return rows


def test_crossfit_reconstructs_conflicting_characteristics_without_price_targets():
    rows = _property_rows()
    rows.append(
        {
            **rows[0],
            "parcel_id": "conflict",
            "char_footprint_sqft": 850.0,
            "char_footprint_gross_sqft": 2_550.0,
            "char_livable_area": 900.0,
            "char_livable_to_footprint_gross_ratio": 900.0 / 2_550.0,
            "char_area_conflict": 1.0,
            "char_beds": 0.0,
            "char_baths": 0.0,
            "sale_price": 1.0,
            "opa_market_value": 99_000_000.0,
        }
    )
    result = crossfit_characteristic_quality(pl.DataFrame(rows), n_folds=3, min_reference_rows=100)
    by_id = {row["parcel_id"]: row for row in result.frame.to_dicts()}
    conflict = by_id["conflict"]

    assert result.metadata["status"] == "ok"
    assert "sale_price" in result.metadata["prohibited_predictors"]
    assert "opa_market_value" in result.metadata["prohibited_predictors"]
    # Tree models do not extrapolate beyond the synthetic footprint range, but
    # they still reconstruct materially more area than the suspect record.
    assert conflict["quality_expected_livable_area"] > 1_200
    assert conflict["quality_area_disagreement_z"] < -3
    assert conflict["quality_expected_beds"] >= 2
    assert conflict["quality_expected_baths"] >= 1
    assert conflict["quality_zero_bed_bath_conflict"] is True
    assert conflict["quality_characteristic_conflict_score"] > 1

    ordinary = by_id["p0001"]
    assert 0.7 < ordinary["quality_area_ratio_to_expected"] < 1.3
    assert ordinary["quality_bed_zero_conflict"] == 0
    assert ordinary["quality_bath_zero_conflict"] == 0


def test_quality_join_has_stable_schema_when_mart_is_missing():
    frame = add_characteristic_quality(pl.DataFrame({"parcel_id": ["p1"]}), None)
    assert set(QUALITY_COLUMNS).issubset(frame.columns)
    assert frame["quality_area_outlier"].to_list() == [False]
    assert frame["quality_expected_livable_area"].to_list() == [None]


def test_quality_audit_reports_learned_cohorts():
    predictions = pl.DataFrame(
        {
            "parcel_id": ["a", "b", "c", "d"],
            "pred_point": [100.0, 200.0, 300.0, 600.0],
            "sale_price": [100.0, 100.0, 300.0, 300.0],
        }
    )
    quality = pl.DataFrame(
        {
            "parcel_id": ["a", "b", "c", "d"],
            "quality_characteristic_outlier": [False, True, False, True],
            "quality_area_outlier": [False, True, False, False],
            "quality_zero_bed_bath_conflict": [False, False, True, True],
        }
    )
    result = evaluate_quality_segments(predictions, quality)
    by_segment = {row["segment"]: row for row in result.to_dicts()}
    assert by_segment["all"]["n"] == 4
    assert by_segment["characteristic_outlier"]["n"] == 2
    assert by_segment["area_outlier"]["n"] == 1
    assert by_segment["zero_bed_bath_conflict"]["n"] == 2
