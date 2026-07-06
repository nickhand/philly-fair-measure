from typing import Any

import httpx
import pyarrow as pa
import pytest
import respx

from philly_fair_measure.sources.carto import (
    PHL_CARTO_URL,
    CartoClient,
    CartoColumn,
    CartoError,
    arrow_schema,
    rows_to_table,
)


def _payload(rows: list[dict[str, Any]], fields: dict | None = None) -> dict[str, Any]:
    return {"rows": rows, "fields": fields or {}, "total_rows": len(rows)}


@pytest.mark.parametrize(
    ("pg_type", "carto_type", "expected"),
    [
        ("int4", "number", pa.int64()),
        ("int8", "number", pa.int64()),
        ("numeric", "number", pa.float64()),
        ("varchar", "string", pa.string()),
        ("text", "string", pa.string()),
        # temporal columns stay raw ISO strings at ingest; parsing is a staging concern
        # (real OPA data contains a year-206 timestamp that would fail a typed cast)
        ("timestamptz", "date", pa.string()),
        ("date", "date", pa.string()),
        ("bytea", None, pa.string()),
        # geometry columns report no pgtype in LIMIT 0 responses; EWKB hex stays a string
        (None, "geometry", pa.string()),
        # aggregate results (e.g. count) report a carto type but no pgtype
        (None, "number", pa.float64()),
    ],
)
def test_arrow_type_mapping(pg_type: str | None, carto_type: str | None, expected: pa.DataType):
    assert CartoColumn("col", carto_type, pg_type).arrow_type() == expected


def test_rows_to_table_preserves_raw_values():
    schema = arrow_schema(
        [
            CartoColumn("sale_date", "date", "timestamptz"),
            CartoColumn("the_geom", "geometry", None),
            CartoColumn("market_value", "number", "numeric"),
        ]
    )
    table = rows_to_table(
        [
            {
                "sale_date": "2023-05-01T00:00:00Z",
                "the_geom": "0101000020E6100000AA",
                "market_value": 405000.0,
            },
            # garbage temporal values seen in real OPA data must survive ingest verbatim
            {"sale_date": "206-04-22T04:56:02Z", "the_geom": None, "market_value": None},
        ],
        schema,
    )
    assert table.num_rows == 2
    assert table.schema.field("sale_date").type == pa.string()
    assert table.column("sale_date").to_pylist() == [
        "2023-05-01T00:00:00Z",
        "206-04-22T04:56:02Z",
    ]
    assert table.column("the_geom").to_pylist() == ["0101000020E6100000AA", None]


@respx.mock
def test_query_raises_carto_error_without_retry():
    route = respx.get(PHL_CARTO_URL).mock(
        return_value=httpx.Response(400, json={"error": ['relation "nope" does not exist']})
    )
    with CartoClient() as client, pytest.raises(CartoError, match="does not exist"):
        client.query("SELECT * FROM nope")
    assert route.call_count == 1


@respx.mock
def test_query_retries_on_503():
    route = respx.get(PHL_CARTO_URL)
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json=_payload([{"n": 1}])),
    ]
    with CartoClient() as client:
        assert client.query("SELECT 1")["rows"] == [{"n": 1}]
    assert route.call_count == 2


@respx.mock
def test_get_columns_and_count():
    fields = {
        "cartodb_id": {"type": "number", "pgtype": "int8"},
        "the_geom": {"type": "geometry"},
        "parcel_number": {"type": "string", "pgtype": "varchar"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sql = request.url.params["q"]
        if "LIMIT 0" in sql:
            return httpx.Response(200, json=_payload([], fields))
        if "count(*)" in sql:
            return httpx.Response(200, json=_payload([{"n": 42}]))
        raise AssertionError(f"unexpected query: {sql}")

    respx.get(PHL_CARTO_URL).mock(side_effect=handler)
    with CartoClient() as client:
        columns = client.get_columns("t")
        assert [c.name for c in columns] == ["cartodb_id", "the_geom", "parcel_number"]
        assert columns[0].pg_type == "int8"
        assert columns[1].pg_type is None
        assert client.count_rows("t") == 42


@respx.mock
def test_iter_pages_uses_keyset_pagination():
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sql = request.url.params["q"]
        queries.append(sql)
        if '"cartodb_id" > 2' in sql:
            return httpx.Response(200, json=_payload([{"cartodb_id": 3, "v": "c"}]))
        return httpx.Response(
            200, json=_payload([{"cartodb_id": 1, "v": "a"}, {"cartodb_id": 2, "v": "b"}])
        )

    respx.get(PHL_CARTO_URL).mock(side_effect=handler)
    with CartoClient() as client:
        pages = list(client.iter_pages("t", columns=["cartodb_id", "v"], page_size=2))

    assert [len(page) for page in pages] == [2, 1]
    assert len(queries) == 2
    assert "WHERE" not in queries[0]
    assert 'ORDER BY "cartodb_id"' in queries[0]
    assert '"cartodb_id" > 2' in queries[1]


@respx.mock
def test_iter_pages_respects_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        sql = request.url.params["q"]
        if "LIMIT 2" in sql:
            return httpx.Response(200, json=_payload([{"cartodb_id": 1}, {"cartodb_id": 2}]))
        if "LIMIT 1" in sql:
            return httpx.Response(200, json=_payload([{"cartodb_id": 3}]))
        raise AssertionError(f"unexpected query: {sql}")

    respx.get(PHL_CARTO_URL).mock(side_effect=handler)
    with CartoClient() as client:
        pages = list(client.iter_pages("t", columns=["cartodb_id"], page_size=2, limit=3))
    assert sum(len(page) for page in pages) == 3


def test_iter_pages_requires_keyset_column():
    with CartoClient() as client, pytest.raises(ValueError, match="cartodb_id"):
        list(client.iter_pages("t", columns=["v"]))
