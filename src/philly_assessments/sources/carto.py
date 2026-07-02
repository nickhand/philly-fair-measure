"""Client for the CARTO SQL API that backs most OpenDataPhilly tabular datasets.

Endpoint: https://phl.carto.com/api/v2/sql?q=<sql>

Facts verified against the live API (2026-07-02, see docs/source_inventory.md):
every phl table carries an indexed ``cartodb_id`` int8 column, so pagination is
keyset-based rather than OFFSET-based; geometry columns come back as hex-encoded
EWKB strings (SRID 4326) and are preserved verbatim; ``the_geom_webmercator`` is
a CARTO-internal reprojection of ``the_geom`` and is excluded from fetches by
default.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import pyarrow as pa
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PHL_CARTO_URL = "https://phl.carto.com/api/v2/sql"
DEFAULT_PAGE_SIZE = 20_000
KEYSET_COLUMN = "cartodb_id"
DEFAULT_EXCLUDED_COLUMNS = ("the_geom_webmercator",)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# pg types observed in phl tables: int4/int8, numeric, varchar, text,
# timestamptz, bytea, plus geometry columns that report no pgtype at all.
# Numbers and booleans are typed natively in the JSON payload, so mapping them
# is lossless. Date/timestamp columns deliberately STAY STRINGS in the raw
# layer: the API serializes them as ISO strings and real tables contain
# unparseable values (opa_properties_public holds a year-206 assessment date),
# so parsing — with per-value status columns — belongs to the staged layer.
# Everything unmapped (identifiers, temporal strings, geometry EWKB hex, bytea)
# is preserved verbatim as a string; the manifest records each column's pg type
# so staging knows what to parse.
_PG_TO_ARROW: dict[str, pa.DataType] = {
    "int2": pa.int64(),
    "int4": pa.int64(),
    "int8": pa.int64(),
    "float4": pa.float64(),
    "float8": pa.float64(),
    "numeric": pa.float64(),
    "bool": pa.bool_(),
}


class CartoError(RuntimeError):
    """The CARTO SQL API returned an error response."""


@dataclass(frozen=True)
class CartoColumn:
    name: str
    carto_type: str | None
    pg_type: str | None

    def arrow_type(self) -> pa.DataType:
        if self.pg_type in _PG_TO_ARROW:
            return _PG_TO_ARROW[self.pg_type]
        if self.pg_type is None and self.carto_type == "number":
            return pa.float64()
        return pa.string()


def arrow_schema(columns: Sequence[CartoColumn]) -> pa.Schema:
    return pa.schema([(column.name, column.arrow_type()) for column in columns])


def rows_to_table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """Convert one page of API rows to Arrow.

    Every schema type mirrors the JSON payload natively (numbers, booleans,
    strings), so no value parsing happens at ingest.
    """
    return pa.Table.from_pylist(rows, schema=schema)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRYABLE_STATUS


class CartoClient:
    def __init__(self, base_url: str = PHL_CARTO_URL, timeout: float = 120.0) -> None:
        self.base_url = base_url
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CartoClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def query(self, sql: str) -> dict[str, Any]:
        response = self._client.get(self.base_url, params={"q": sql})
        if response.status_code in _RETRYABLE_STATUS:
            response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise CartoError(f"non-JSON response for {sql!r}") from None
        if "error" in payload:
            raise CartoError(f"CARTO error for {sql!r}: {payload['error']}")
        response.raise_for_status()
        return payload

    def get_columns(self, table: str) -> list[CartoColumn]:
        payload = self.query(f'SELECT * FROM "{table}" LIMIT 0')
        return [
            CartoColumn(name=name, carto_type=meta.get("type"), pg_type=meta.get("pgtype"))
            for name, meta in payload.get("fields", {}).items()
        ]

    def count_rows(self, table: str) -> int:
        payload = self.query(f'SELECT count(*) AS n FROM "{table}"')
        return int(payload["rows"][0]["n"])

    def iter_pages(
        self,
        table: str,
        *,
        columns: Sequence[str],
        page_size: int = DEFAULT_PAGE_SIZE,
        limit: int | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of rows ordered by the keyset column.

        OFFSET pagination degrades and can skip/duplicate rows on multi-million-row
        tables, so pages advance via ``WHERE cartodb_id > <last seen>`` instead.
        """
        if KEYSET_COLUMN not in columns:
            raise ValueError(f"columns must include {KEYSET_COLUMN!r} for keyset pagination")
        column_list = ", ".join(f'"{name}"' for name in columns)
        last_id: int | None = None
        fetched = 0
        while True:
            size = page_size if limit is None else min(page_size, limit - fetched)
            if size <= 0:
                return
            where = "" if last_id is None else f' WHERE "{KEYSET_COLUMN}" > {last_id}'
            sql = (
                f'SELECT {column_list} FROM "{table}"{where} '
                f'ORDER BY "{KEYSET_COLUMN}" LIMIT {size}'
            )
            rows = self.query(sql)["rows"]
            if not rows:
                return
            yield rows
            fetched += len(rows)
            last_id = rows[-1][KEYSET_COLUMN]
            if len(rows) < size:
                return
