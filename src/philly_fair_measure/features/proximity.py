"""Per-parcel proximity features: SEPTA stations, parks, road class.

The last unbuilt feature family from the OPA-parity plan (feature-plan-v2.md;
CCAO ships transit/road proximity in production). All layers were live-
verified 2026-07-03: SEPTA's own ArcGIS org hosts the station layers
(Broad_Street_Line_Stations 24, Market_Frankford_Line_Stations 28,
Regional_Rail_Stations 155 — regionwide, nearest-distance picks the Philly
ones), the city org hosts PPR_Properties (506 park polygons) and
Street_Centerline (41,271 segments; `class` 1=expressway, 2-3=arterial,
4-5=collector/local; `st_code` joins OPA's street_code 3,436/3,436).

Quasi-static: distances change only when infrastructure does, so the mart is
keyed by parcel_id and joined into the sale/assessment/condo feature builds.
Expressway distance is kept separate from arterial distance — one is a
disamenity, the other a corridor-access signal; the model learns the signs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure import catalog, config
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef

logger = logging.getLogger(__name__)

RAPID_TRANSIT_DATASETS = ("septa_bsl_stations", "septa_mfl_stations")
REGIONAL_RAIL_DATASET = "septa_regional_rail"
PARKS_DATASET = "ppr_properties"
CENTERLINE_DATASET = "street_centerline"

PROX_COLUMNS = [
    "prox_dist_rapid_transit_m",
    "prox_dist_regional_rail_m",
    "prox_dist_park_m",
    "prox_dist_expressway_m",
    "prox_dist_arterial_m",
    # CCAO free-quadrant round two (2026-07-04). prox_dist_vacant_land_m is
    # semi-static (vacancy persists for years but does change) — the honest
    # caveat class sits between quasi-static and current_only.
    "prox_n_bus_stops_800m",
    "prox_dist_bike_network_m",
    "prox_parcel_density_400m",
    "prox_dist_vacant_land_m",
]
BUS_STOPS_DATASET = "septa_bus_stops"
BIKE_NETWORK_DATASET = "bike_network"
_BUS_RADIUS_M = 800.0
_DENSITY_RADIUS_M = 400.0
STREET_CLASS_COLUMN = "loc_street_class"

_EXPRESSWAY_CLASSES = (1,)
_ARTERIAL_CLASSES = (2, 3)


def _project_geoms(geojson: np.ndarray) -> npt.NDArray[np.object_]:
    """Parse GeoJSON strings and project to the shared tangent plane (meters)."""
    import shapely
    from shapely import from_geojson

    from philly_fair_measure.features.market_areas import _LAT0, _LON0

    geoms = from_geojson(geojson, on_invalid="ignore")
    valid = np.array([g is not None and not g.is_empty for g in geoms])
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = m_per_deg_lat * np.cos(np.deg2rad(_LAT0))

    def to_meters(coords: np.ndarray) -> np.ndarray:
        out = np.empty_like(coords)
        out[:, 0] = (coords[:, 0] - _LON0) * m_per_deg_lon
        out[:, 1] = (coords[:, 1] - _LAT0) * m_per_deg_lat
        return out

    projected = shapely.transform(geoms[valid], to_meters)
    return np.asarray(projected, dtype=object)


def _nearest_distance(target_xy: np.ndarray, geoms: npt.NDArray[np.object_]) -> np.ndarray:
    """Distance (m) from each target point to the nearest geometry (0 inside)."""
    from shapely import STRtree, points

    out = np.full(len(target_xy), np.nan)
    if len(geoms) == 0:
        return out
    located = np.isfinite(target_xy).all(axis=1)
    tree = STRtree(geoms)
    _, dist = tree.query_nearest(
        points(target_xy[located]), return_distance=True, all_matches=False
    )
    out[located] = dist
    return out


def _street_class(centerline: pl.DataFrame) -> pl.DataFrame:
    """Modal street class per st_code (a street's segments can differ)."""
    return (
        centerline.drop_nulls(["st_code", "class"])
        .group_by("st_code", "class")
        .len()
        .sort("len", descending=True)
        .unique(subset=["st_code"], keep="first")
        .select(
            pl.col("st_code").cast(pl.String).str.strip_chars_start("0").alias("_street_code"),
            pl.col("class").cast(pl.String).alias(STREET_CLASS_COLUMN),
        )
    )


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_proximity(data_dir: Path | None = None) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    latest = catalog.latest_snapshots(data_dir)
    needed = [
        *RAPID_TRANSIT_DATASETS,
        REGIONAL_RAIL_DATASET,
        PARKS_DATASET,
        CENTERLINE_DATASET,
        BUS_STOPS_DATASET,
        BIKE_NETWORK_DATASET,
    ]
    missing = [d for d in needed if d not in latest]
    if missing:
        raise FileNotFoundError(
            f"missing raw snapshots {missing}; see docs/operations.md for the "
            "snapshot commands (SEPTA layers need --org septa)"
        )

    from philly_fair_measure.features.market_areas import project_xy

    parcels = (
        pl.scan_parquet(root / "staged" / "opa_properties.parquet")
        .select(
            "parcel_number",
            "street_code",
            "category_code_description",
            "lon",
            "lat",
            "lonlat_status",
        )
        .collect()
        .with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
    )
    xy = parcels.select("x_m", "y_m").cast(pl.Float64).to_numpy()
    xy[parcels["lonlat_status"].fill_null("").to_numpy() != "ok"] = np.nan

    def load_geoms(dataset: str, predicate: pl.Expr | None = None) -> npt.NDArray[np.object_]:
        lf = pl.scan_parquet(latest[dataset].data_path)
        if predicate is not None:
            lf = lf.filter(predicate)
        geojson = lf.select("geometry_geojson").collect()["geometry_geojson"]
        return _project_geoms(geojson.to_numpy())

    rapid = np.concatenate([load_geoms(d) for d in RAPID_TRANSIT_DATASETS])
    regional = load_geoms(REGIONAL_RAIL_DATASET)
    parks = load_geoms(PARKS_DATASET)
    expressways = load_geoms(CENTERLINE_DATASET, pl.col("class").is_in(list(_EXPRESSWAY_CLASSES)))
    arterials = load_geoms(CENTERLINE_DATASET, pl.col("class").is_in(list(_ARTERIAL_CLASSES)))
    logger.info(
        "proximity targets: %d rapid-transit, %d regional-rail, %d parks, "
        "%d expressway segs, %d arterial segs",
        len(rapid),
        len(regional),
        len(parks),
        len(expressways),
        len(arterials),
    )

    bus = load_geoms(BUS_STOPS_DATASET)
    bike = load_geoms(BIKE_NETWORK_DATASET)
    logger.info("round two: %d bus stops, %d bike segments", len(bus), len(bike))

    from scipy.spatial import cKDTree

    located = np.isfinite(xy).all(axis=1)
    bus_counts = np.full(len(xy), np.nan)
    density = np.full(len(xy), np.nan)
    if len(bus):
        import shapely

        bus_xy = np.array([[g.x, g.y] for g in bus if isinstance(g, shapely.Point)])
        bus_tree = cKDTree(bus_xy)
        bus_counts[located] = [
            float(len(ix)) for ix in bus_tree.query_ball_point(xy[located], _BUS_RADIUS_M)
        ]
    parcel_tree = cKDTree(xy[located])
    density[located] = (
        np.array(
            parcel_tree.query_ball_point(xy[located], _DENSITY_RADIUS_M, return_length=True),
            dtype=float,
        )
        - 1.0
    )

    is_vacant = (
        (parcels["category_code_description"].cast(pl.String) == "VACANT LAND")
        .fill_null(False)
        .to_numpy()
    )
    vacant_xy = xy[is_vacant & located]
    dist_vacant = np.full(len(xy), np.nan)
    if len(vacant_xy):
        vtree = cKDTree(vacant_xy)
        d, _ix = vtree.query(xy[located], k=1, workers=-1)
        dist_vacant[located] = d
    logger.info("vacant-land parcels located: %d", len(vacant_xy))

    frame = parcels.select(
        pl.col("parcel_number").alias("parcel_id"),
        pl.col("street_code").cast(pl.String).str.strip_chars_start("0").alias("_street_code"),
    ).with_columns(
        pl.Series("prox_dist_rapid_transit_m", _nearest_distance(xy, rapid)).fill_nan(None),
        pl.Series("prox_dist_regional_rail_m", _nearest_distance(xy, regional)).fill_nan(None),
        pl.Series("prox_dist_park_m", _nearest_distance(xy, parks)).fill_nan(None),
        pl.Series("prox_dist_expressway_m", _nearest_distance(xy, expressways)).fill_nan(None),
        pl.Series("prox_dist_arterial_m", _nearest_distance(xy, arterials)).fill_nan(None),
        pl.Series("prox_n_bus_stops_800m", bus_counts).fill_nan(None),
        pl.Series("prox_dist_bike_network_m", _nearest_distance(xy, bike)).fill_nan(None),
        pl.Series("prox_parcel_density_400m", density).fill_nan(None),
        pl.Series("prox_dist_vacant_land_m", dist_vacant).fill_nan(None),
    )
    centerline = (
        pl.scan_parquet(latest[CENTERLINE_DATASET].data_path).select("st_code", "class").collect()
    )
    frame = frame.join(_street_class(centerline), on="_street_code", how="left").drop(
        "_street_code"
    )

    inputs = [InputRef(dataset=latest[d].dataset, fetched_at=latest[d].fetched_at) for d in needed]
    path, manifest = write_derived_table(
        frame,
        root,
        "marts",
        "proximity",
        inputs,
        notes="quasi-static per-parcel proximity features",
    )
    return BuildResult(path=path, manifest=manifest)
