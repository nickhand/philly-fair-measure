import polars as pl

from philly_assessments.diagnostics.acs_sensitivity import join_tracts


def _square(lon0, lat0, size=0.01):
    return (
        '{"type":"Polygon","coordinates":[['
        + ",".join(
            f"[{lon},{lat}]"
            for lon, lat in [
                (lon0, lat0),
                (lon0 + size, lat0),
                (lon0 + size, lat0 + size),
                (lon0, lat0 + size),
                (lon0, lat0),
            ]
        )
        + "]]}"
    )


def test_join_tracts_point_in_polygon():
    acs = pl.DataFrame(
        {
            "acs_geoid": ["t1", "t2", "bad"],
            "acs_pct_white": [0.2, 0.8, 0.5],
            "acs_pct_black": [0.7, 0.1, 0.3],
            "acs_pct_hispanic": [0.05, 0.05, 0.1],
            "acs_pct_asian": [0.05, 0.05, 0.1],
            "acs_median_income": [30_000.0, 90_000.0, 50_000.0],
            "acs_poverty_rate": [0.4, 0.05, 0.2],
            "acs_majority_race": ["Black", "White", "None"],
            "geometry_geojson": [
                _square(-75.20, 39.94),
                _square(-75.16, 39.94),
                "not json",  # invalid geometry must be skipped, not fatal
            ],
        }
    )
    df = pl.DataFrame(
        {
            "sale_id": ["a", "b", "c", "d"],
            "loc_lon": [-75.195, -75.155, -75.50, None],  # t1, t2, outside, unlocated
            "loc_lat": [39.945, 39.945, 39.945, None],
        }
    )
    out = join_tracts(df, acs)
    by = {row["sale_id"]: row for row in out.to_dicts()}
    assert by["a"]["acs_geoid"] == "t1"
    assert by["a"]["acs_majority_race"] == "Black"
    assert by["b"]["acs_median_income"] == 90_000.0
    assert by["c"]["acs_geoid"] is None
    assert by["d"]["acs_geoid"] is None
    assert out.height == df.height
