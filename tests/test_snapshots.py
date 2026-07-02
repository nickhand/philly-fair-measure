import hashlib
import json
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import respx

from philly_assessments.ingest.manifests import read_manifest
from philly_assessments.ingest.snapshots import snapshot_carto_table
from philly_assessments.sources.carto import PHL_CARTO_URL

FIELDS = {
    "cartodb_id": {"type": "number", "pgtype": "int8"},
    "the_geom": {"type": "geometry"},
    "the_geom_webmercator": {"type": "geometry"},
    "parcel_number": {"type": "string", "pgtype": "varchar"},
    "market_value": {"type": "number", "pgtype": "numeric"},
    "sale_date": {"type": "date", "pgtype": "timestamptz"},
}

PAGE_ONE = [
    {
        "cartodb_id": 1,
        "the_geom": "0101000020E6100000AA",
        "parcel_number": "012345678",
        "market_value": 405000.0,
        "sale_date": "2023-05-01T00:00:00Z",
    },
    {
        "cartodb_id": 2,
        "the_geom": None,
        "parcel_number": "012345679",
        "market_value": None,
        "sale_date": None,
    },
]
PAGE_TWO = [
    {
        "cartodb_id": 3,
        "the_geom": None,
        "parcel_number": "012345680",
        "market_value": 12000.0,
        "sale_date": "2020-01-15T00:00:00Z",
    },
]


def _payload(rows: list[dict[str, Any]], fields: dict | None = None) -> dict[str, Any]:
    return {"rows": rows, "fields": fields or {}, "total_rows": len(rows)}


def _handler(request: httpx.Request) -> httpx.Response:
    sql = request.url.params["q"]
    if "LIMIT 0" in sql:
        return httpx.Response(200, json=_payload([], FIELDS))
    if "count(*)" in sql:
        return httpx.Response(200, json=_payload([{"n": 3}]))
    assert "the_geom_webmercator" not in sql, "excluded column must not be fetched"
    if '"cartodb_id" > 2' in sql:
        return httpx.Response(200, json=_payload(PAGE_TWO))
    return httpx.Response(200, json=_payload(PAGE_ONE))


@respx.mock
def test_snapshot_carto_table_end_to_end(tmp_path):
    respx.get(PHL_CARTO_URL).mock(side_effect=_handler)

    result = snapshot_carto_table("opa_test", data_dir=tmp_path, page_size=2)

    # layout: data/raw/source=carto/dataset=<name>/fetched_at=<ts>/
    assert result.directory.parent.name == "dataset=opa_test"
    assert result.directory.parent.parent.name == "source=carto"
    assert result.directory.name.startswith("fetched_at=")
    assert not list(result.directory.parent.glob("*.incomplete"))

    table = pq.read_table(result.directory / "data.parquet")
    assert table.num_rows == 3
    assert "the_geom_webmercator" not in table.schema.names
    assert table.schema.field("sale_date").type == pa.string()
    assert table.schema.field("market_value").type == pa.float64()
    assert table.column("parcel_number").to_pylist() == ["012345678", "012345679", "012345680"]

    manifest = read_manifest(result.directory)
    assert manifest.source == "carto"
    assert manifest.dataset == "opa_test"
    assert manifest.row_count == 3
    assert manifest.source_row_count == 3
    assert manifest.num_pages == 2
    assert manifest.order_key == "cartodb_id"
    assert manifest.excluded_columns == ["the_geom_webmercator"]
    assert [c.name for c in manifest.columns] == [
        "cartodb_id",
        "the_geom",
        "parcel_number",
        "market_value",
        "sale_date",
    ]

    (file_info,) = manifest.files
    data_bytes = (result.directory / file_info.path).read_bytes()
    assert file_info.size_bytes == len(data_bytes)
    assert file_info.sha256 == hashlib.sha256(data_bytes).hexdigest()

    # manifest.json is valid JSON on disk
    raw = json.loads((result.directory / "manifest.json").read_text())
    assert raw["manifest_version"] == 1


@respx.mock
def test_snapshot_respects_limit(tmp_path):
    respx.get(PHL_CARTO_URL).mock(side_effect=_handler)
    result = snapshot_carto_table("opa_test", data_dir=tmp_path, page_size=2, limit=2)
    assert result.manifest.row_count == 2
    assert result.manifest.row_limit == 2
