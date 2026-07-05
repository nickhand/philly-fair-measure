import polars as pl
from fastapi.testclient import TestClient

from philly_assessments.api import create_app
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import InputRef


def _screen_rows() -> list[dict]:
    def row(pid, addr, lon, lat, opa, model, ratio, z, flag, twin_n=6, twin_med=1.0):
        return {
            "_lon": lon, "_lat": lat,  # consumed by the features fixture, not the screen
            "parcel_id": pid, "address": addr, "char_category": "SINGLE FAMILY",
            "opa_market_value": opa, "model_median": model,
            "model_pi_low_90": model * 0.7, "model_pi_high_90": model * 1.4,
            "opa_vs_model_ratio": ratio, "screen_z": z, "assessment_flag": flag,
            "interval_method": "bayesian_posterior", "model_family": "residential",
            "twin_n": twin_n, "opa_vs_twin_median": twin_med,
            "aerial_change_flag": False, "aerial_pair": None,
            "evt_n_vacant_complaints_5y_before": 0.0,
            "evt_n_unpermitted_work_complaints_5y_before": 1.0,
            "dist_tax_delinquent": 0.0, "ten_rental_license_at_sale": 0.0,
            "shp_n_linked_parcels": 1.0,
        }

    rows = [
        row("p1", "108 ELFRETHS ALY", -75.1425, 39.9527, 441_900.0, 520_000.0,
            0.85, -0.4, "within_range"),
        row("p2", "110 ELFRETHS ALY", -75.1426, 39.9528, 900_000.0, 300_000.0,
            3.0, 5.0, "over_assessed_candidate"),
        row("p3", "9 FAKE ST", -75.20, 39.99, 65_000.0, 400_000.0,
            0.16, -6.0, "under_assessed_candidate"),
    ]
    rows += [
        row(f"w{i}", f"{100 + i} MARKET ST", -75.15 + i * 1e-4, 39.951, 200_000.0,
            210_000.0, 0.95, 0.1, "within_range")
        for i in range(15)
    ]
    return rows


def _features_rows(screen: list[dict]) -> list[dict]:
    return [
        {"parcel_id": r["parcel_id"], "address": r["address"],
         "char_category": "SINGLE FAMILY",
         "loc_lon": r["_lon"], "loc_lat": r["_lat"], "loc_zip5": "19106"}
        for r in screen
    ]


def _client(tmp_path) -> TestClient:
    screen = _screen_rows()
    screen_cols = [{k: v for k, v in r.items() if not k.startswith("_")} for r in screen]
    write_derived_table(
        pl.DataFrame(screen_cols), tmp_path, "marts", "assessment_screen",
        [InputRef(dataset="t", fetched_at="t")],
    )
    write_derived_table(
        pl.DataFrame(_features_rows(screen)), tmp_path, "marts", "assessment_features",
        [InputRef(dataset="t", fetched_at="t")],
    )
    return TestClient(create_app(tmp_path))


def test_stats_counts_flags(tmp_path):
    c = _client(tmp_path)
    body = c.get("/api/stats").json()
    assert body["properties"] == 18
    assert body["over"] == 1 and body["under"] == 1 and body["within"] == 16
    assert 0.5 < body["median_ratio"] < 1.1


def test_search_ranks_prefix_first(tmp_path):
    c = _client(tmp_path)
    hits = c.get("/api/search", params={"q": "elfreths"}).json()
    assert {h["parcel_id"] for h in hits} == {"p1", "p2"}  # case-insensitive
    hits = c.get("/api/search", params={"q": "108 ELF"}).json()
    assert hits[0]["parcel_id"] == "p1"  # prefix match ranks first
    assert c.get("/api/search", params={"q": "x"}).status_code == 422  # min length


def test_property_core_and_404(tmp_path):
    c = _client(tmp_path)
    body = c.get("/api/property/p2").json()
    assert body["flag"] == "over_assessed_candidate"
    assert body["opa_market_value"] == 900_000.0
    assert body["lon"] == -75.1426 and body["lat"] == 39.9528
    assert body["signals"]["unpermitted_work_complaints_5y"] == 1
    assert c.get("/api/property/nope").status_code == 404


def test_parcels_bbox_filters(tmp_path):
    c = _client(tmp_path)
    fc = c.get(
        "/api/parcels",
        params={"minx": -75.16, "miny": 39.94, "maxx": -75.14, "maxy": 39.96},
    ).json()
    ids = {f["properties"]["id"] for f in fc["features"]}
    assert "p1" in ids and "p3" not in ids  # p3 is outside the box
    assert fc["features"][0]["geometry"]["type"] == "Point"


def test_report_degrades_without_model_artifacts(tmp_path):
    c = _client(tmp_path)
    body = c.get("/api/property/p1/report").json()
    # no model run / staged tables in the fixture: panels degrade to null/empty
    assert body["drivers"] is None
    assert body["assessment_history"] == []
    assert body["sale_history"] == []


def test_flagged_parcels_returns_only_over_under(tmp_path):
    c = _client(tmp_path)
    fc = c.get("/api/parcels/flagged").json()
    flags = {f["properties"]["flag"] for f in fc["features"]}
    ids = {f["properties"]["id"] for f in fc["features"]}
    assert flags == {"over_assessed_candidate", "under_assessed_candidate"}
    assert ids == {"p2", "p3"}  # the within-range majority stays out
    # cached second call returns the same payload
    assert c.get("/api/parcels/flagged").json() == fc


def test_admin_leaderboard_kinds(tmp_path):
    c = _client(tmp_path)
    over = c.get("/api/admin/leaderboard", params={"kind": "over", "n": 5}).json()
    assert over and over[0]["parcel_id"] == "p2"
    assert c.get("/api/admin/leaderboard", params={"kind": "bogus"}).status_code == 422
