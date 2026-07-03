import numpy as np
import polars as pl

from philly_assessments.features.proximity import (
    _nearest_distance,
    _project_geoms,
    _street_class,
)


def test_project_and_nearest_distance():
    from philly_assessments.features.market_areas import project_xy

    # a station point and a park polygon, both defined in lon/lat
    geojson = np.array(
        [
            '{"type":"Point","coordinates":[-75.16,39.95]}',
            '{"type":"Polygon","coordinates":[[[-75.15,39.95],[-75.14,39.95],'
            '[-75.14,39.96],[-75.15,39.96],[-75.15,39.95]]]}',
            "garbage",  # invalid geometry must be skipped, not fatal
        ]
    )
    geoms = _project_geoms(geojson)
    assert len(geoms) == 2

    targets = (
        pl.DataFrame({"lon": [-75.16, -75.145], "lat": [39.95, 39.955]})
        .with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
        .select("x_m", "y_m")
        .cast(pl.Float64)
        .to_numpy()
    )
    d_station = _nearest_distance(targets, geoms[:1])
    assert d_station[0] < 1.0  # standing on the station
    assert 1000 < d_station[1] < 2000  # ~1.3km east
    d_park = _nearest_distance(targets, geoms[1:])
    assert d_park[1] == 0.0  # inside the polygon
    assert d_park[0] > 500

    # unlocated targets stay null-ish (NaN)
    d_nan = _nearest_distance(np.array([[np.nan, np.nan]]), geoms)
    assert np.isnan(d_nan[0])


def test_street_class_modal_per_code():
    centerline = pl.DataFrame(
        {
            "st_code": [100, 100, 100, 200, None],
            "class": [2, 2, 4, 5, 3],
        }
    )
    out = _street_class(centerline)
    by = {row["_street_code"]: row["loc_street_class"] for row in out.to_dicts()}
    assert by["100"] == "2"  # modal class wins
    assert by["200"] == "5"
