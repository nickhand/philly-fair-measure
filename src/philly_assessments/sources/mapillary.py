"""Minimal Mapillary Graph API client (street-level imagery metadata).

Imagery is crowdsourced and CC BY-SA 4.0; the token is a free client access
token read from the MAPILLARY_TOKEN environment variable (or a repo-root
.env, which is gitignored — never commit tokens). Verified live 2026-07-03.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.mapillary.com/images"
DEFAULT_FIELDS = "id,captured_at,computed_geometry,compass_angle,is_pano,thumb_1024_url"

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_token() -> str:
    if "MAPILLARY_TOKEN" not in os.environ:
        _load_dotenv()
    token = os.environ.get("MAPILLARY_TOKEN")
    if not token:
        raise RuntimeError(
            "MAPILLARY_TOKEN not set; create a free client token at "
            "mapillary.com/dashboard/developers and export it or put it in .env"
        )
    return token


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRYABLE_STATUS


class MapillaryClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        self._token = token or get_token()
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MapillaryClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def images_in_bbox(
        self,
        bbox: tuple[float, float, float, float],
        *,
        fields: str = DEFAULT_FIELDS,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Image metadata within a WGS84 (lon0, lat0, lon1, lat1) bbox."""
        response = self._client.get(
            GRAPH_URL,
            params={
                "access_token": self._token,
                "bbox": ",".join(f"{v:.7f}" for v in bbox),
                "fields": fields,
                "limit": limit,
            },
        )
        if response.status_code in _RETRYABLE_STATUS:
            response.raise_for_status()
        response.raise_for_status()
        return cast(list[dict[str, Any]], response.json().get("data", []))
