from __future__ import annotations

import polars as pl

from philly_fair_measure.features.property_state import add_property_state_features


def test_property_state_separates_active_distressed_and_entity_conflict():
    frame = pl.DataFrame(
        {
            "parcel_id": ["stable", "shell", "active", "multi"],
            "char_category": ["SINGLE FAMILY", "SINGLE FAMILY", "SINGLE FAMILY", "MULTI FAMILY"],
            "char_interior_condition": ["4", "7", "4", "4"],
            "char_exterior_condition": ["4", "6", "4", "4"],
            "char_livable_area": [1_200.0, 1_100.0, 1_300.0, 900.0],
            "char_lot_area": [900.0, 900.0, 900.0, 1_000.0],
            "char_footprint_sqft": [600.0, 550.0, 650.0, 850.0],
            "char_beds": [3, 3, 3, 0],
            "char_baths": [1, 1, 2, 0],
            "shp_parcel_num_accounts": [1, 1, 1, 3],
            "shp_parcel_num_brt": [1, 1, 1, 2],
            "shp_n_linked_parcels": [0, 0, 1, 0],
            "evt_n_active_change_occupancy_at_sale": [0, 0, 1, 0],
            "evt_n_active_reno_permits_at_sale": [0, 0, 1, 0],
            "evt_n_active_permits_at_sale": [0, 0, 2, 0],
            "evt_n_completed_reno_permits_5y_before": [0, 0, 0, 0],
            "evt_n_open_severe_at_sale": [0, 1, 0, 0],
            "evt_n_severe_violations_5y_before": [0, 2, 0, 0],
            "evt_n_vacant_complaints_5y_before": [0, 1, 0, 0],
            "evt_n_demolitions_before": [0, 0, 0, 0],
            "dist_sheriff_sale": [0, 1, 0, 0],
            "dist_tax_delinquent": [0, 1, 0, 0],
            "quality_characteristic_conflict_score": [0.0, 0.0, 0.0, 1.8],
            "char_area_conflict": [0, 0, 0, 1],
            "char_new_build": [0, 0, 0, 0],
            # These prohibited outcome columns must have no role.
            "sale_price": [100.0, 999_999.0, 1.0, 50_000.0],
            "opa_market_value": [200.0, 1.0, 999_999.0, 60_000.0],
        }
    )

    result = add_property_state_features(frame).sort("parcel_id")
    rows = {row["parcel_id"]: row for row in result.to_dicts()}

    assert rows["stable"]["state_primary_evidence"] == "stable_or_unknown"
    assert rows["shell"]["state_primary_evidence"] == "distressed"
    assert rows["shell"]["state_distress_evidence"] > 0.95
    assert rows["active"]["state_primary_evidence"] == "active_work"
    assert rows["active"]["state_active_work_evidence"] > 0.95
    assert rows["active"]["entity_assemblage"] == 1.0
    assert rows["multi"]["entity_multi_account"] == 1.0
    assert rows["multi"]["entity_multifamily_zero_unit_conflict"] == 1.0
    assert rows["multi"]["entity_livable_area_per_account"] == 300.0
    assert rows["multi"]["state_measurement_conflict_evidence"] == 1.0


def test_property_state_tolerates_sparse_fixture():
    result = add_property_state_features(pl.DataFrame({"parcel_id": ["x"]}))
    assert result["state_primary_evidence"][0] == "stable_or_unknown"
    assert result["entity_account_count"][0] == 1.0
