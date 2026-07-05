"""Parcel shape features from PWD parcel polygons (plan v2 Tier 2.1).

CCAO's parcel-geometry features survived their production pruning (see
docs/ccao-lessons.md); this module computes the same set from the raw
PWD_PARCELS snapshot, in projected meters on the shared local tangent plane:

    shp_parcel_area_m2, shp_parcel_perimeter_m
    shp_parcel_num_vertices          exterior ring vertices (closing point excluded)
    shp_parcel_edge_len_sd_m         SD of exterior edge lengths
    shp_parcel_interior_angle_sd_deg SD of interior vertex angles
    shp_parcel_centroid_dist_sd_m    SD of vertex distance to the centroid
    shp_parcel_mrr_area_ratio        parcel area / minimum rotated rectangle area
    shp_parcel_mrr_side_ratio        longest / shortest MRR side

plus the PWD attribute bridge: `brt_id` (OPA account), `num_brt` and
`num_accounts` (multi-account parcels — the house + side-yard signal).

MultiPolygons contribute their largest part. Output grain: one row per
`brt_id` (largest parcel wins when an account spans several PWD parcels),
because the feature marts join on OPA account.
"""

from __future__ import annotations

import logging

import numpy as np
import numpy.typing as npt
import polars as pl

logger = logging.getLogger(__name__)

_MIN_RING_POINTS = 4  # closed triangle


def _tangent_project(geoms: npt.NDArray[np.object_]) -> npt.NDArray[np.object_]:
    """Project WGS84 geometries to meters on the shared local tangent plane."""
    import math

    import shapely

    from philly_assessments.features.market_areas import _LAT0, _LON0, _M_PER_DEG_LAT

    m_per_deg_lon = 111_320.0 * math.cos(math.radians(_LAT0))

    def to_meters(coords: np.ndarray) -> np.ndarray:
        out = np.empty_like(coords)
        out[:, 0] = (coords[:, 0] - _LON0) * m_per_deg_lon
        out[:, 1] = (coords[:, 1] - _LAT0) * _M_PER_DEG_LAT
        return out

    return np.asarray(shapely.transform(geoms, to_meters), dtype=object)


def _ring_stats(geoms: npt.NDArray[np.object_]) -> dict[str, np.ndarray]:
    """Vectorized per-polygon exterior-ring statistics via reduceat on the
    flattened coordinate array."""
    import shapely

    rings = shapely.get_exterior_ring(geoms)
    coords, ring_ix = shapely.get_coordinates(rings, return_index=True)
    n = len(geoms)

    counts = np.bincount(ring_ix, minlength=n)  # includes the closing point
    starts = np.zeros(n, dtype=np.int64)
    starts[1:] = np.cumsum(counts)[:-1]

    num_vertices = np.where(counts >= _MIN_RING_POINTS, counts - 1, 0)

    edge_sd = np.full(n, np.nan)
    angle_sd = np.full(n, np.nan)
    centroid_sd = np.full(n, np.nan)
    cent = shapely.centroid(geoms)
    # get_x raises on empty points (empty-polygon placeholders); those rows
    # never enter the loop below, so any dummy coordinate works
    cent = np.where(shapely.is_empty(cent), shapely.Point(0.0, 0.0), cent)
    centroids = np.column_stack([shapely.get_x(cent), shapely.get_y(cent)])
    for i in range(n):
        m = counts[i]
        if m < _MIN_RING_POINTS:
            continue
        ring = coords[starts[i] : starts[i] + m - 1]  # open ring (unique vertices)
        edges = np.diff(np.vstack([ring, ring[:1]]), axis=0)
        lengths = np.hypot(edges[:, 0], edges[:, 1])
        edge_sd[i] = lengths.std()
        # interior angle at each vertex: angle between incoming and outgoing edges
        incoming = np.roll(edges, 1, axis=0)
        dot = (incoming * edges).sum(axis=1)
        cross = incoming[:, 0] * edges[:, 1] - incoming[:, 1] * edges[:, 0]
        angles = np.degrees(np.pi - np.arctan2(cross, dot))
        angle_sd[i] = (np.mod(angles, 360.0)).std()
        centroid_sd[i] = np.hypot(*(ring - centroids[i]).T).std()

    return {
        "shp_parcel_num_vertices": num_vertices.astype(np.float64),
        "shp_parcel_edge_len_sd_m": edge_sd,
        "shp_parcel_interior_angle_sd_deg": angle_sd,
        "shp_parcel_centroid_dist_sd_m": centroid_sd,
    }


def _mrr_ratios(geoms: npt.NDArray[np.object_]) -> dict[str, np.ndarray]:
    import shapely

    mrr = shapely.oriented_envelope(geoms)
    area_ratio = np.where(shapely.area(mrr) > 0, shapely.area(geoms) / shapely.area(mrr), np.nan)
    coords, ix = shapely.get_coordinates(shapely.get_exterior_ring(mrr), return_index=True)
    side_ratio = np.full(len(geoms), np.nan)
    counts = np.bincount(ix, minlength=len(geoms))
    starts = np.zeros(len(geoms), dtype=np.int64)
    starts[1:] = np.cumsum(counts)[:-1]
    for i in range(len(geoms)):
        if counts[i] < 5:  # rectangle ring = 5 closed points
            continue
        rect = coords[starts[i] : starts[i] + 4 + 1]
        sides = np.hypot(*np.diff(rect, axis=0).T)[:2]
        if sides.min() > 0:
            side_ratio[i] = sides.max() / sides.min()
    return {
        "shp_parcel_mrr_area_ratio": area_ratio,
        "shp_parcel_mrr_side_ratio": side_ratio,
    }


def parcel_shape_features(geojson: pl.Series) -> pl.DataFrame:
    """Shape features for a series of GeoJSON polygon strings (row-aligned)."""
    import shapely

    geoms = shapely.from_geojson(geojson.fill_null("").to_numpy(), on_invalid="ignore")
    # MultiPolygons -> largest part; invalid/missing -> empty placeholder
    multi = shapely.get_type_id(geoms) == 6  # MultiPolygon
    if multi.any():
        for i in np.flatnonzero(multi):
            parts = shapely.get_parts(geoms[i])
            geoms[i] = parts[np.argmax(shapely.area(parts))]
    valid = (shapely.get_type_id(geoms) == 3) & ~shapely.is_empty(geoms)  # Polygon
    geoms = np.where(valid, geoms, shapely.Polygon())

    projected = _tangent_project(geoms)
    columns: dict[str, np.ndarray] = {
        "shp_parcel_area_m2": shapely.area(projected),
        "shp_parcel_perimeter_m": shapely.length(projected),
    }
    columns.update(_ring_stats(projected))
    columns.update(_mrr_ratios(projected))

    out = pl.DataFrame({name: values for name, values in columns.items()})
    return out.with_columns(
        *[
            pl.when(pl.Series(valid)).then(pl.col(c)).otherwise(None).fill_nan(None)
            for c in out.columns
        ]
    )


MAX_OWNER_PARCELS = 20  # owners above this are institutional; not side-yard cases
ADJACENCY_DISTANCE_M = 0.3


def _owner_links(frame: pl.DataFrame, geoms: npt.NDArray[np.object_]) -> pl.DataFrame:
    """Per-parcel owner-linked adjacency: neighboring parcels (within
    ADJACENCY_DISTANCE_M) held by the same small (non-institutional) owner —
    the house + side-yard pattern. Adds shp_n_linked_parcels and
    shp_linked_lot_area_m2 (own + linked area)."""
    import shapely

    owner = frame["owner_norm"].fill_null("").to_numpy()
    counts = frame.group_by("owner_norm").len().rename({"len": "owner_parcels"})
    frame_counts = frame.join(counts, on="owner_norm", how="left")
    linkable = (
        (frame_counts["owner_parcels"].fill_null(0) <= MAX_OWNER_PARCELS).to_numpy()
        & (owner != "")  # null owners can't join their group count; excluded here
        & ~shapely.is_empty(geoms)
    )

    n = len(frame)
    n_linked = np.zeros(n, dtype=np.int64)
    linked_area = shapely.area(geoms).copy()
    tree = shapely.STRtree(geoms[linkable])
    linkable_ix = np.flatnonzero(linkable)
    pairs = tree.query(geoms[linkable], predicate="dwithin", distance=ADJACENCY_DISTANCE_M)
    a = linkable_ix[pairs[0]]
    b = linkable_ix[pairs[1]]
    mask = (a != b) & (owner[a] == owner[b])
    a, b = a[mask], b[mask]
    np.add.at(n_linked, a, 1)
    np.add.at(linked_area, a, shapely.area(geoms[b]))
    return frame.with_columns(
        pl.Series("shp_n_linked_parcels", n_linked),
        pl.Series("shp_linked_lot_area_m2", np.where(n_linked > 0, linked_area, np.nan)).fill_nan(
            None
        ),
    ).drop("owner_norm")


def stg_parcels(raw: pl.LazyFrame, raw_opa: pl.LazyFrame) -> pl.LazyFrame:
    """PWD parcels with shape features and owner-linked adjacency, one row per
    OPA account (brt_id). Owner comes from the OPA roll (fresher than PWD)."""
    import shapely

    frame = raw.select(
        "parcelid",
        "brt_id",
        "num_brt",
        "num_accounts",
        "gross_area",
        "pin",
        "address",
        "geometry_geojson",
    ).collect()
    owners = raw_opa.select(
        pl.col("parcel_number").alias("brt_id"),
        pl.col("owner_1")
        .cast(pl.String)
        .str.to_uppercase()
        .str.replace_all(r"[^A-Z0-9]", "")
        .alias("owner_norm"),
    ).collect()
    frame = frame.join(owners, on="brt_id", how="left")

    geojson = frame["geometry_geojson"]
    shapes = parcel_shape_features(geojson)
    geoms = shapely.from_geojson(geojson.fill_null("").to_numpy(), on_invalid="ignore")
    geoms = np.where(
        (shapely.get_type_id(geoms) >= 3) & ~shapely.is_empty(geoms),
        geoms,
        shapely.Polygon(),
    )
    geoms = _tangent_project(geoms)

    frame = pl.concat([frame.drop("geometry_geojson"), shapes], how="horizontal")
    frame = _owner_links(frame, geoms)
    out = (
        frame.filter(pl.col("brt_id").is_not_null() & (pl.col("brt_id") != ""))
        .sort("shp_parcel_area_m2", descending=True, nulls_last=True)
        .unique(subset=["brt_id"], keep="first")
        .sort("brt_id")
    )
    return out.lazy()
