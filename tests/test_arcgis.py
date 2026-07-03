import json

import httpx
import polars as pl
import pytest
import respx

from philly_assessments.ingest.snapshots import snapshot_arcgis_layer
from philly_assessments.sources.arcgis import PHL_ARCGIS_BASE, ArcGISClient, ArcGISError

LAYER_URL = f"{PHL_ARCGIS_BASE}/TEST_SVC/FeatureServer/0"

FIELDS_META = {
    "fields": [
        {"name": "objectid", "type": "esriFieldTypeOID"},
        {"name": "brt_id", "type": "esriFieldTypeString"},
        {"name": "num_brt", "type": "esriFieldTypeInteger"},
        {"name": "gross_area", "type": "esriFieldTypeDouble"},
    ]
}


def _feature(oid, brt="123456789"):
    return {
        "type": "Feature",
        "properties": {"objectid": oid, "brt_id": brt, "num_brt": 1, "gross_area": 900.0},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-75.16, 39.95], [-75.159, 39.95], [-75.159, 39.951],
                             [-75.16, 39.951], [-75.16, 39.95]]],
        },
    }


def _handler(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if params.get("f") == "json" and "where" not in params:
        return httpx.Response(200, json=FIELDS_META)
    if params.get("returnCountOnly") == "true":
        return httpx.Response(200, json={"count": 3})
    where = params.get("where", "")
    if "objectid > 0" in where:
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": [_feature(1), _feature(2)]}
        )
    if "objectid > 2" in where:
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": [_feature(3)]}
        )
    return httpx.Response(200, json={"type": "FeatureCollection", "features": []})


@respx.mock
def test_iter_pages_keyset_and_geometry_roundtrip():
    respx.get(f"{LAYER_URL}/query").mock(side_effect=_handler)
    respx.get(LAYER_URL).mock(return_value=httpx.Response(200, json=FIELDS_META))
    with ArcGISClient() as client:
        pages = list(client.iter_pages("TEST_SVC", page_size=2))
    # a trailing empty page proves exhaustion (short pages don't: servers may
    # cap resultRecordCount below the request)
    assert [len(p) for p in pages] == [2, 1]
    geom = json.loads(pages[0][0]["geometry_geojson"])
    assert geom["type"] == "Polygon"
    assert len(geom["coordinates"][0]) == 5


@respx.mock
def test_arcgis_error_in_200_payload_raises():
    respx.get(f"{LAYER_URL}/query").mock(
        return_value=httpx.Response(200, json={"error": {"code": 400, "message": "bad"}})
    )
    with ArcGISClient() as client, pytest.raises(ArcGISError, match="bad"):
        client.count("TEST_SVC")


@respx.mock
def test_snapshot_arcgis_layer_end_to_end(tmp_path):
    respx.get(f"{LAYER_URL}/query").mock(side_effect=_handler)
    respx.get(LAYER_URL).mock(return_value=httpx.Response(200, json=FIELDS_META))

    result = snapshot_arcgis_layer("TEST_SVC", data_dir=tmp_path)
    assert result.directory.parent.parent.name == "source=arcgis"
    assert result.manifest.source == "arcgis"
    assert result.manifest.row_count == 3
    assert result.manifest.source_row_count == 3
    assert result.manifest.order_key == "objectid"

    table = pl.read_parquet(result.directory / "data.parquet")
    assert table.height == 3
    assert table["num_brt"].dtype == pl.Int64
    assert table["gross_area"].dtype == pl.Float64
    assert json.loads(table["geometry_geojson"][0])["type"] == "Polygon"
