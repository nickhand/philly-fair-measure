import re

import polars as pl
from fastapi.testclient import TestClient

from philly_fair_measure.api import create_app
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef


def _screen_rows() -> list[dict]:
    def row(pid, addr, lon, lat, opa, model, ratio, z, flag, twin_n=6, twin_med=1.0):
        return {
            "_lon": lon,
            "_lat": lat,  # consumed by the features fixture, not the screen
            "parcel_id": pid,
            "address": addr,
            "char_category": "SINGLE FAMILY",
            "opa_market_value": opa,
            "model_median": model,
            "model_pi_low_90": model * 0.7,
            "model_pi_high_90": model * 1.4,
            "opa_vs_model_ratio": ratio,
            # Stage 5 role separation: surfaces read display_*; the fixture
            # keeps both machines identical so expectations stay simple
            "display_median": model,
            "display_ratio": ratio,
            "screen_z": z,
            "assessment_flag": flag,
            "attention": ("high" if z > 1 else "low" if z < -1 else None)
            if flag == "within_range"
            else None,
            "interval_method": "bayesian_posterior",
            "model_family": "residential",
            "twin_n": twin_n,
            "opa_vs_twin_median": twin_med,
            "aerial_change_flag": False,
            "aerial_pair": None,
            "evt_n_vacant_complaints_5y_before": 0.0,
            "evt_n_unpermitted_work_complaints_5y_before": 1.0,
            "dist_tax_delinquent": 0.0,
            "ten_rental_license_at_sale": 0.0,
            "shp_n_linked_parcels": 1.0,
        }

    rows = [
        row(
            "p1",
            "108 ELFRETHS ALY",
            -75.1425,
            39.9527,
            441_900.0,
            520_000.0,
            0.85,
            -0.4,
            "within_range",
        ),
        row(
            "p2",
            "110 ELFRETHS ALY",
            -75.1426,
            39.9528,
            900_000.0,
            300_000.0,
            3.0,
            5.0,
            "over_assessed_candidate",
        ),
        row(
            "p3",
            "9 FAKE ST",
            -75.20,
            39.99,
            65_000.0,
            400_000.0,
            0.16,
            -6.0,
            "under_assessed_candidate",
        ),
    ]
    rows += [
        row(
            f"w{i}",
            f"{100 + i} MARKET ST",
            -75.15 + i * 1e-4,
            39.951,
            200_000.0,
            210_000.0,
            0.95,
            0.1,
            "within_range",
        )
        for i in range(15)
    ]
    rows[0]["quality_area_outlier"] = True
    rows[0]["record_quality_warning"] = True
    return rows


def _features_rows(screen: list[dict]) -> list[dict]:
    return [
        {
            "parcel_id": r["parcel_id"],
            "address": r["address"],
            "char_category": "SINGLE FAMILY",
            "loc_lon": r["_lon"],
            "loc_lat": r["_lat"],
            "loc_zip5": "19106",
        }
        for r in screen
    ]


def _client(tmp_path, screen: list[dict] | None = None) -> TestClient:
    screen = screen if screen is not None else _screen_rows()
    screen_cols = [{k: v for k, v in r.items() if not k.startswith("_")} for r in screen]
    write_derived_table(
        pl.DataFrame(screen_cols),
        tmp_path,
        "marts",
        "assessment_screen",
        [InputRef(dataset="t", fetched_at="t")],
    )
    write_derived_table(
        pl.DataFrame(_features_rows(screen)),
        tmp_path,
        "marts",
        "assessment_features",
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

    warning = c.get("/api/property/p1").json()
    assert warning["quality_reasons"] == ["learned_area_outlier"]
    assert warning["data_quality_warning"] is True


def test_parcels_bbox_filters(tmp_path):
    c = _client(tmp_path)
    fc = c.get(
        "/api/parcels",
        params={"minx": -75.16, "miny": 39.94, "maxx": -75.14, "maxy": 39.96},
    ).json()
    ids = {f["properties"]["id"] for f in fc["features"]}
    assert "p1" in ids and "p3" not in ids  # p3 is outside the box
    assert fc["features"][0]["geometry"]["type"] == "Point"
    # the watch tier rides along for the map's tinted dots
    assert "attention" in fc["features"][0]["properties"]


def test_parcels_bbox_says_when_the_limit_drops_homes(tmp_path):
    c = _client(tmp_path)
    box = {"minx": -75.16, "miny": 39.94, "maxx": -75.14, "maxy": 39.96}
    every = c.get("/api/parcels", params=box).json()
    in_view = len(every["features"])
    assert every["type"] == "FeatureCollection" and every["truncated"] is False

    capped = c.get("/api/parcels", params={**box, "limit": in_view - 1}).json()
    assert len(capped["features"]) == in_view - 1
    assert capped["truncated"] is True

    exact = c.get("/api/parcels", params={**box, "limit": in_view}).json()
    assert len(exact["features"]) == in_view and exact["truncated"] is False


def test_parcels_bbox_keeps_highlighted_homes_under_the_limit(tmp_path):
    def home(pid: str, i: int, flag: str, attention: str | None = None) -> dict:
        return {
            **_screen_rows()[3],
            "parcel_id": pid,
            "address": f"{200 + i} MARKET ST",
            "_lon": -75.15 + i * 1e-4,
            "assessment_flag": flag,
            "attention": attention,
        }

    # the mart lists the homes the map highlights after the quiet majority
    screen = [
        *(home(f"r{i}", i, "within_range") for i in range(6)),
        home("d2", 6, "insufficient_record"),
        home("d1", 7, "insufficient_record"),
        home("w2", 8, "within_range", "high"),
        home("w1", 9, "within_range", "low"),
        home("u1", 10, "under_assessed_candidate"),
        home("o1", 11, "over_assessed_candidate"),
    ]
    box = {"minx": -75.16, "miny": 39.94, "maxx": -75.14, "maxy": 39.96}

    def served(rows: list[dict], name: str, limit: int) -> set[str]:
        c = _client(tmp_path / name, rows)
        fc = c.get("/api/parcels", params={**box, "limit": limit}).json()
        assert fc["truncated"] is True
        return {f["properties"]["id"] for f in fc["features"]}

    # flagged first, then the watch tier, then data warnings, then the rest
    assert served(screen, "a", 2) == {"u1", "o1"}
    assert served(screen, "b", 4) == {"u1", "o1", "w1", "w2"}
    assert served(screen, "c", 6) == {"u1", "o1", "w1", "w2", "d1", "d2"}
    # a cut inside one group keeps the same homes whatever the mart's row order
    assert served(screen, "d", 3) == served(screen[::-1], "e", 3)
    assert served(screen, "f", 5) == served(screen[::-1], "g", 5)


def test_report_degrades_without_model_artifacts(tmp_path):
    c = _client(tmp_path)
    body = c.get("/api/property/p1/report").json()
    # no model run / staged tables in the fixture: panels degrade to null/empty
    assert body["drivers"] is None
    assert body["assessment_history"] == []
    assert body["sale_history"] == []


def test_flagged_parcels_returns_flags_and_watch_tier(tmp_path):
    c = _client(tmp_path)
    fc = c.get("/api/parcels/flagged").json()
    flags = {f["properties"]["flag"] for f in fc["features"]}
    ids = {f["properties"]["id"] for f in fc["features"]}
    assert flags == {"over_assessed_candidate", "under_assessed_candidate"}
    assert ids == {"p2", "p3"}  # comfortable within-range majority stays out
    # watch tier rides along when present (fixture has none: p1 has |z| < 1),
    # but the property is always emitted for the map's tier styling
    assert all("attention" in f["properties"] for f in fc["features"])
    # cached second call returns the same payload
    assert c.get("/api/parcels/flagged").json() == fc


def test_flagged_parcels_revalidate_with_an_etag(tmp_path):
    c = _client(tmp_path)
    first = c.get("/api/parcels/flagged")
    assert first.status_code == 200
    etag = first.headers["etag"]
    # the payload changes only on a deploy, so a cached copy may live briefly
    max_age = int(re.search(r"max-age=(\d+)", first.headers["cache-control"]).group(1))
    assert 0 < max_age <= 300

    unchanged = c.get("/api/parcels/flagged", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == etag

    other = c.get("/api/parcels/flagged", headers={"If-None-Match": 'W/"another-payload"'})
    assert other.status_code == 200
    assert other.json() == first.json()

    # new data behind a deploy must not match the old validator
    screen = _screen_rows()
    screen[1]["opa_market_value"] = 950_000.0
    redeployed = _client(tmp_path / "next", screen).get("/api/parcels/flagged")
    assert redeployed.headers["etag"] != etag


def test_admin_leaderboard_kinds(tmp_path):
    c = _client(tmp_path)
    over = c.get("/api/admin/leaderboard", params={"kind": "over", "n": 5}).json()
    assert over and over[0]["parcel_id"] == "p2"
    assert c.get("/api/admin/leaderboard", params={"kind": "bogus"}).status_code == 422
