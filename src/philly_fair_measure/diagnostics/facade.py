"""Facade-imagery pipeline, stage 1: Mapillary coverage check (the go/no-go).

Before any vision model gets built, measure whether Mapillary's crowdsourced
street imagery actually covers Philadelphia's residential parcels with usable
facade views. "Usable" requires geometry, not just proximity: the image must
sit 4-45m from the parcel point and either be a 360 pano or have its camera
heading within FACING_TOLERANCE_DEG of the bearing toward the parcel.

Output: per-parcel best-image rows + coverage rates overall, by district, and
by capture recency. Stage 2 (embedding + OPA-label probe) only happens if
this gate passes; docs/research-notes.md records the verdict either way.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.scalars import as_float

logger = logging.getLogger(__name__)

RADIUS_M = 40.0
MIN_DIST_M = 4.0
MAX_DIST_M = 45.0
FACING_TOLERANCE_DEG = 55.0
_M_PER_DEG_LAT = 111_132.0


def _usable_images(images: list[dict], lon: float, lat: float) -> list[dict]:
    m_per_deg_lon = _M_PER_DEG_LAT * np.cos(np.deg2rad(lat))
    out = []
    for img in images:
        geom = (img.get("computed_geometry") or {}).get("coordinates")
        if not geom:
            continue
        dx = (lon - geom[0]) * m_per_deg_lon
        dy = (lat - geom[1]) * _M_PER_DEG_LAT
        dist = float(np.hypot(dx, dy))
        if not (MIN_DIST_M <= dist <= MAX_DIST_M):
            continue
        if not img.get("is_pano"):
            heading = img.get("compass_angle")
            if heading is None:
                continue
            bearing = float(np.degrees(np.arctan2(dx, dy))) % 360.0
            diff = abs((bearing - float(heading) + 180.0) % 360.0 - 180.0)
            if diff > FACING_TOLERANCE_DEG:
                continue
        out.append(
            {
                "image_id": img["id"],
                "captured_year": datetime.fromtimestamp(img["captured_at"] / 1000, UTC).year,
                "distance_m": dist,
                "is_pano": bool(img.get("is_pano")),
                "thumb_url": img.get("thumb_1024_url"),
            }
        )
    return out


def facade_coverage(
    data_dir: Path | None = None,
    *,
    n_sample: int = 2000,
    workers: int = 8,
    seed: int = 42,
) -> pl.DataFrame:
    """Sample residential parcels stratified by district; query Mapillary for
    a usable facade image per parcel; persist per-parcel results."""
    from philly_fair_measure.ingest.derived import write_derived_table
    from philly_fair_measure.sources.mapillary import MapillaryClient

    root = data_dir if data_dir is not None else config.data_dir()
    parcels = (
        pl.scan_parquet(root / "marts" / "assessment_features.parquet")
        .filter(
            pl.col("loc_lon").is_not_null()
            & pl.col("loc_lat").is_not_null()
            & pl.col("loc_district").is_not_null()
        )
        .select("parcel_id", "loc_lon", "loc_lat", "loc_district", "char_exterior_condition")
        .collect()
    )
    per_district = max(20, n_sample // parcels["loc_district"].n_unique())
    sample = (
        parcels.sample(fraction=1.0, shuffle=True, seed=seed)
        .group_by("loc_district", maintain_order=True)
        .head(per_district)
    )
    logger.info("facade coverage: querying %d parcels", sample.height)

    rows = sample.to_dicts()
    client = MapillaryClient()

    def process(row: dict) -> dict:
        lon, lat = row["loc_lon"], row["loc_lat"]
        dlat = RADIUS_M / _M_PER_DEG_LAT
        dlon = RADIUS_M / (_M_PER_DEG_LAT * np.cos(np.deg2rad(lat)))
        try:
            images = client.images_in_bbox((lon - dlon, lat - dlat, lon + dlon, lat + dlat))
        except Exception:  # noqa: BLE001 — coverage stats just mark the failure
            return {**_empty(row), "query_ok": False}
        usable = _usable_images(images, lon, lat)
        if not usable:
            return {**_empty(row), "query_ok": True, "n_images_nearby": len(images)}
        best = max(usable, key=lambda u: (u["captured_year"], -u["distance_m"]))
        return {
            "parcel_id": row["parcel_id"],
            "loc_district": row["loc_district"],
            "char_exterior_condition": row["char_exterior_condition"],
            "query_ok": True,
            "n_images_nearby": len(images),
            "n_usable": len(usable),
            "best_image_id": best["image_id"],
            "best_year": best["captured_year"],
            "best_distance_m": best["distance_m"],
            "best_is_pano": best["is_pano"],
            "best_thumb_url": best["thumb_url"],
        }

    def _empty(row: dict) -> dict:
        return {
            "parcel_id": row["parcel_id"],
            "loc_district": row["loc_district"],
            "char_exterior_condition": row["char_exterior_condition"],
            "query_ok": True,
            "n_images_nearby": 0,
            "n_usable": 0,
            "best_image_id": None,
            "best_year": None,
            "best_distance_m": None,
            "best_is_pano": None,
            "best_thumb_url": None,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(process, rows))
    client.close()

    table = pl.DataFrame(results)
    write_derived_table(
        table,
        root,
        "diagnostics",
        "facade_coverage",
        [],
        notes=f"mapillary usable-facade coverage; radius {RADIUS_M}m, "
        f"facing tol {FACING_TOLERANCE_DEG} deg",
    )
    return table


def coverage_summary(table: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(overall-by-recency, by-district) coverage rates."""
    ok = table.filter(pl.col("query_ok"))
    overall = pl.DataFrame(
        [
            {
                "cut": "any usable image",
                "coverage": as_float((ok["n_usable"] > 0).mean()),
            },
            {
                "cut": "usable, captured 2020+",
                "coverage": as_float((ok["best_year"].fill_null(0) >= 2020).mean()),
            },
            {
                "cut": "usable, captured 2023+",
                "coverage": as_float((ok["best_year"].fill_null(0) >= 2023).mean()),
            },
        ]
    )
    by_district = (
        ok.group_by("loc_district")
        .agg(
            (pl.col("n_usable") > 0).mean().round(3).alias("any_usable"),
            (pl.col("best_year").fill_null(0) >= 2020).mean().round(3).alias("usable_2020plus"),
            pl.len().alias("n"),
        )
        .sort("any_usable", descending=True)
    )
    return overall, by_district
