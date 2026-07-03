"""Client for ArcGIS FeatureServer layers (City of Philadelphia org).

Facts verified against the live PWD_PARCELS layer (2026-07-03): layers cap
responses at maxRecordCount=2000; `objectid` keyset pagination works via
`where=objectid > <last>` + `orderByFields=objectid`; `f=geojson` +
`outSR=4326` returns WGS84 GeoJSON features. Geometry is preserved verbatim as
a GeoJSON string column (`geometry_geojson`) — parsing belongs to staging.

Esri date fields arrive as epoch milliseconds in GeoJSON properties and are
kept as raw integers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pyarrow as pa
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PHL_ARCGIS_BASE = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services"
# SEPTA's own ArcGIS org (station layers live there, not in the city org;
# verified live 2026-07-03: Broad_Street_Line_Stations 24, Market_Frankford_
# Line_Stations 28, Regional_Rail_Stations 155)
SEPTA_ARCGIS_BASE = "https://services2.arcgis.com/9U43PSoL47wawX5S/ArcGIS/rest/services"
DEFAULT_PAGE_SIZE = 2000
KEYSET_FIELD = "objectid"
GEOMETRY_COLUMN = "geometry_geojson"

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_ESRI_TO_ARROW: dict[str, pa.DataType] = {
    "esriFieldTypeOID": pa.int64(),
    "esriFieldTypeInteger": pa.int64(),
    "esriFieldTypeSmallInteger": pa.int64(),
    "esriFieldTypeBigInteger": pa.int64(),
    "esriFieldTypeDouble": pa.float64(),
    "esriFieldTypeSingle": pa.float64(),
    "esriFieldTypeDate": pa.int64(),  # epoch milliseconds, kept raw
}


class ArcGISError(RuntimeError):
    """The ArcGIS REST API returned an error response."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    # in-payload REST errors ("Unable to perform query", code 400) are usually
    # transient capacity blips (verified 2026-07-03: the same Street_Centerline
    # query failed once and succeeded on immediate retry); genuinely bad
    # queries still fail after the attempt budget
    if isinstance(exc, ArcGISError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRYABLE_STATUS


class ArcGISClient:
    def __init__(self, base_url: str = PHL_ARCGIS_BASE, timeout: float = 120.0) -> None:
        self.base_url = base_url
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ArcGISClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def layer_url(self, service: str, layer: int = 0) -> str:
        return f"{self.base_url}/{service}/FeatureServer/{layer}"

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._client.get(url, params=params)
        if response.status_code in _RETRYABLE_STATUS:
            response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise ArcGISError(f"non-JSON response from {url}") from None
        # the REST API reports errors inside a 200 payload
        if isinstance(payload, dict) and "error" in payload:
            raise ArcGISError(f"ArcGIS error from {url}: {payload['error']}")
        response.raise_for_status()
        return payload

    def get_fields(self, service: str, layer: int = 0) -> list[dict[str, Any]]:
        meta = self._get(self.layer_url(service, layer), {"f": "json"})
        return [
            {"name": f["name"], "esri_type": f.get("type"), "alias": f.get("alias")}
            for f in meta.get("fields", [])
        ]

    def count(self, service: str, layer: int = 0) -> int:
        payload = self._get(
            self.layer_url(service, layer) + "/query",
            {"where": "1=1", "returnCountOnly": "true", "f": "json"},
        )
        return int(payload["count"])

    def oid_field(self, service: str, layer: int = 0) -> str:
        """The layer's ObjectID field name (case varies by layer: objectid,
        OBJECTID, ...)."""
        for f in self.get_fields(service, layer):
            if f["esri_type"] == "esriFieldTypeOID":
                return f["name"]
        return KEYSET_FIELD

    def iter_pages(
        self,
        service: str,
        layer: int = 0,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        keyset_field: str | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of flattened rows: properties + geometry as GeoJSON string."""
        url = self.layer_url(service, layer) + "/query"
        key = keyset_field or self.oid_field(service, layer)
        last_id = 0
        while True:
            payload = self._get(
                url,
                {
                    "where": f"{key} > {last_id}",
                    "outFields": "*",
                    "outSR": 4326,
                    "orderByFields": key,
                    "resultRecordCount": page_size,
                    "f": "geojson",
                },
            )
            features = payload.get("features", [])
            if not features:
                return
            rows = []
            for feature in features:
                row = dict(feature["properties"])
                geometry = feature.get("geometry")
                row[GEOMETRY_COLUMN] = None if geometry is None else json.dumps(geometry)
                rows.append(row)
            yield rows
            last_id = features[-1]["properties"][key]
            # no short-page early exit: servers may silently cap
            # resultRecordCount below the request (maxRecordCount varies by
            # layer), so only an empty page proves exhaustion


def arrow_schema(fields: list[dict[str, Any]]) -> pa.Schema:
    columns = [
        (f["name"], _ESRI_TO_ARROW.get(f["esri_type"] or "", pa.string())) for f in fields
    ]
    columns.append((GEOMETRY_COLUMN, pa.string()))
    return pa.schema(columns)
