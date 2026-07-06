"""Boot the API against deploy/data and exercise every endpoint.

The deploy bundle is a curated subset of the data lake; this proves the
subset is complete (a missing file fails loudly here instead of in prod).
Runs the app in-process with FastAPI's TestClient — no port juggling.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BUNDLE = Path("deploy/data")


def main() -> int:
    if not BUNDLE.exists():
        print("deploy/data missing — run `just bundle-data` first")
        return 1
    os.environ["PHILLY_DATA_DIR"] = str(BUNDLE)
    os.environ["PHILLY_ENV"] = "prod"
    os.environ.pop("PHILLY_ADMIN_TOKEN", None)

    from fastapi.testclient import TestClient

    from philly_fair_measure.api import create_app

    client = TestClient(create_app())

    def check(label: str, path: str, ok=None, headers=None) -> object:
        res = client.get(path, headers=headers)
        assert res.status_code == 200, f"{label}: {res.status_code} for {path}"
        body = res.json()
        if ok is not None:
            assert ok(body), f"{label}: unexpected body for {path}"
        print(f"  ok  {label}")
        return body

    check("health", "/health", lambda b: b["status"] == "ok" and b["rows"] > 400_000)
    stats = check("stats", "/api/stats", lambda b: b["properties"] > 400_000)
    print(f"      ({stats['properties']:,} properties, {stats['over'] + stats['under']:,} flagged)")

    hits = check("search", "/api/search?q=ELFRETHS", lambda b: len(b) > 0)
    rowhome = hits[0]["parcel_id"]
    check(f"property {rowhome}", f"/api/property/{rowhome}")
    check(
        "report (residential)",
        f"/api/property/{rowhome}/report",
        lambda b: b["drivers"] is not None and len(b["assessment_history"]) > 0,
    )
    check("comps (residential)", f"/api/property/{rowhome}/comps", lambda b: len(b) > 0)

    condo = client.get("/api/search?q=3600 CONSHOHOCKEN AVE %231001").json()[0]["parcel_id"]
    check(
        "report (condo)",
        f"/api/property/{condo}/report",
        lambda b: b["drivers"] is not None and b["equity"] is not None,
    )
    check("comps (condo)", f"/api/property/{condo}/comps", lambda b: len(b) > 0)

    check(
        "parcels bbox",
        "/api/parcels?minx=-75.17&miny=39.94&maxx=-75.14&maxy=39.96",
        lambda b: len(b["features"]) > 100,
    )
    check("parcels flagged", "/api/parcels/flagged", lambda b: len(b["features"]) > 1_000)

    # prod posture: admin is denied without a configured token
    res = client.get("/api/admin/leaderboard?kind=over")
    assert res.status_code == 404, f"admin should 404 in prod without a token: {res.status_code}"
    print("  ok  admin locked in prod")

    print("smoke test passed — the bundle serves every endpoint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
