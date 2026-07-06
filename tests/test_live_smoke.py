"""Smoke tests against the real CARTO API. Deselected by default; run with -m live."""

import pytest

from philly_fair_measure.sources.carto import CartoClient

pytestmark = pytest.mark.live


def test_fetch_five_rows_from_opa_properties():
    with CartoClient() as client:
        payload = client.query(
            "SELECT cartodb_id, parcel_number, market_value"
            " FROM opa_properties_public ORDER BY cartodb_id LIMIT 5"
        )
    rows = payload["rows"]
    assert len(rows) == 5
    assert all(row["parcel_number"] for row in rows)


def test_schema_probe_matches_inventory_expectations():
    with CartoClient() as client:
        columns = {c.name for c in client.get_columns("assessments")}
    assert {"cartodb_id", "parcel_number", "year", "market_value"} <= columns
