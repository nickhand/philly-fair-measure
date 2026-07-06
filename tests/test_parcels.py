import json
import math

import polars as pl
import pytest

from philly_fair_measure.staging.parcels import parcel_shape_features, stg_parcels

_LON0, _LAT0 = -75.16, 39.95
_M_LON = 111_320.0 * math.cos(math.radians(_LAT0))
_M_LAT = 110_540.0


def _poly(points_m, holes=None):
    """GeoJSON polygon from vertices given in meters on the tangent plane."""
    ring = [[_LON0 + x / _M_LON, _LAT0 + y / _M_LAT] for x, y in points_m]
    ring.append(ring[0])
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


SQUARE_100 = _poly([(0, 0), (100, 0), (100, 100), (0, 100)])
RECT_200x50 = _poly([(0, 0), (200, 0), (200, 50), (0, 50)])
L_SHAPE = _poly([(0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100)])


def test_square_shape_features():
    out = parcel_shape_features(pl.Series([SQUARE_100])).to_dicts()[0]
    assert out["shp_parcel_area_m2"] == pytest.approx(10_000, rel=1e-3)
    assert out["shp_parcel_perimeter_m"] == pytest.approx(400, rel=1e-3)
    assert out["shp_parcel_num_vertices"] == 4
    assert out["shp_parcel_edge_len_sd_m"] == pytest.approx(0.0, abs=0.5)
    assert out["shp_parcel_interior_angle_sd_deg"] == pytest.approx(0.0, abs=1.0)
    assert out["shp_parcel_centroid_dist_sd_m"] == pytest.approx(0.0, abs=0.5)
    assert out["shp_parcel_mrr_area_ratio"] == pytest.approx(1.0, abs=0.02)
    assert out["shp_parcel_mrr_side_ratio"] == pytest.approx(1.0, abs=0.02)


def test_rectangle_and_l_shape():
    out = parcel_shape_features(pl.Series([RECT_200x50, L_SHAPE]))
    rect, ell = out.to_dicts()
    assert rect["shp_parcel_mrr_side_ratio"] == pytest.approx(4.0, rel=0.02)
    assert rect["shp_parcel_mrr_area_ratio"] == pytest.approx(1.0, abs=0.02)
    # L: 3/4 of its bounding square, six vertices, one reflex angle -> angle SD > 0
    assert ell["shp_parcel_num_vertices"] == 6
    assert ell["shp_parcel_area_m2"] == pytest.approx(7_500, rel=1e-3)
    assert ell["shp_parcel_mrr_area_ratio"] == pytest.approx(0.75, abs=0.02)
    assert ell["shp_parcel_interior_angle_sd_deg"] > 30


def test_multipolygon_uses_largest_part_and_invalid_is_null():
    big = json.loads(SQUARE_100)["coordinates"]
    small = json.loads(_poly([(500, 0), (510, 0), (510, 10), (500, 10)]))["coordinates"]
    multi = json.dumps({"type": "MultiPolygon", "coordinates": [small, big]})
    out = parcel_shape_features(pl.Series([multi, None, "{}"]))
    rows = out.to_dicts()
    assert rows[0]["shp_parcel_area_m2"] == pytest.approx(10_000, rel=1e-3)
    assert rows[1]["shp_parcel_area_m2"] is None
    assert rows[2]["shp_parcel_area_m2"] is None


def _opa_owners(rows):
    return pl.LazyFrame([{"parcel_number": brt, "owner_1": owner} for brt, owner in rows])


def test_stg_parcels_dedupes_brt_keeping_largest():
    raw = pl.LazyFrame(
        {
            "parcelid": [1, 2, 3, 4],
            "brt_id": ["111", "111", "222", ""],
            "num_brt": [2, 2, 1, 1],
            "num_accounts": [2, 2, 1, 1],
            "gross_area": [900, 100, 500, 10],
            "pin": [1, 2, 3, 4],
            "address": ["A ST", "A REAR", "B ST", "NO BRT"],
            "geometry_geojson": [
                SQUARE_100,
                _poly([(0, 0), (10, 0), (10, 10), (0, 10)]),
                L_SHAPE,
                None,
            ],
        }
    )
    owners = _opa_owners([("111", "SMITH J"), ("222", "DOE A")])
    out = stg_parcels(raw, owners).collect()
    assert out["brt_id"].to_list() == ["111", "222"]
    row = out.filter(pl.col("brt_id") == "111").to_dicts()[0]
    assert row["parcelid"] == 1  # largest parcel wins
    assert row["shp_parcel_num_vertices"] == 4
    assert row["num_brt"] == 2


def test_owner_linked_adjacency_side_yard_case():
    # house (100x100 at origin) + touching side yard (50 wide), same owner;
    # a touching neighbor with a different owner; a same-owner parcel far away
    house = SQUARE_100
    side_yard = _poly([(100, 0), (150, 0), (150, 100), (100, 100)])
    neighbor = _poly([(-50, 0), (0, 0), (0, 100), (-50, 100)])
    far_same_owner = _poly([(5000, 0), (5100, 0), (5100, 100), (5000, 100)])
    raw = pl.LazyFrame(
        {
            "parcelid": [1, 2, 3, 4],
            "brt_id": ["h1", "y1", "n1", "f1"],
            "num_brt": [1] * 4,
            "num_accounts": [1] * 4,
            "gross_area": [100] * 4,
            "pin": [1, 2, 3, 4],
            "address": ["1 A ST", "3 A ST", "5 A ST", "9 Z ST"],
            "geometry_geojson": [house, side_yard, neighbor, far_same_owner],
        }
    )
    owners = _opa_owners(
        [("h1", "Hand, Nick"), ("y1", "HAND NICK"), ("n1", "OTHER OWNER"), ("f1", "hand nick")]
    )
    out = stg_parcels(raw, owners).collect()
    by = {r["brt_id"]: r for r in out.to_dicts()}
    assert by["h1"]["shp_n_linked_parcels"] == 1  # side yard, not the far parcel
    assert by["h1"]["shp_linked_lot_area_m2"] == pytest.approx(15_000, rel=0.01)
    assert by["y1"]["shp_n_linked_parcels"] == 1
    assert by["n1"]["shp_n_linked_parcels"] == 0
    assert by["f1"]["shp_n_linked_parcels"] == 0
    assert by["n1"]["shp_linked_lot_area_m2"] is None


def test_institutional_owners_not_linked():
    # 25 adjacent parcels under one owner: institutional, must not link
    raw_rows = []
    owner_rows = []
    for i in range(25):
        raw_rows.append(
            {
                "parcelid": i,
                "brt_id": f"b{i}",
                "num_brt": 1,
                "num_accounts": 1,
                "gross_area": 100,
                "pin": i,
                "address": f"{i} PHA ST",
                "geometry_geojson": _poly(
                    [(i * 100, 0), (i * 100 + 100, 0), (i * 100 + 100, 100), (i * 100, 100)]
                ),
            }
        )
        owner_rows.append((f"b{i}", "PHILA HOUSING AUTHORITY"))
    out = stg_parcels(pl.LazyFrame(raw_rows), _opa_owners(owner_rows)).collect()
    assert (out["shp_n_linked_parcels"] == 0).all()
