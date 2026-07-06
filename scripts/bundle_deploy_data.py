"""Assemble the minimal data bundle the API needs at serve time.

Writes deploy/data/ (gitignored) for the Docker build. Everything the API
reads per request is included; the two large history tables are trimmed to
the columns the endpoints actually touch. Run `just api-smoke` afterwards to
boot the API against the bundle and exercise every endpoint before deploying.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from philly_assessments import config  # noqa: E402
from philly_assessments.models.scoring import latest_run_dir  # noqa: E402

OUT = Path("deploy/data")

# copied whole: the API reads full rows (report drivers, comps, coordinates)
FULL_COPIES = [
    "marts/assessment_screen.parquet",
    "marts/assessment_features.parquet",
    "marts/condo_assessment_features.parquet",
    "marts/condo_sale_features.parquet",
    "marts/sale_features.parquet",  # residential comps pool
]

# trimmed to the columns the endpoints read (they are the bundle's big files)
TRIMS: dict[str, list[str]] = {
    # /report sale history (_histories)
    "marts/sale_validity.parquet": [
        "parcel_id",
        "sale_date",
        "sale_price",
        "deed_kind",
        "validity_status",
    ],
    # /report assessment history (_histories)
    "staged/assessments.parquet": ["parcel_number", "year_parsed", "market_value"],
    # comps address join (find_comps)
    "staged/opa_properties.parquet": ["parcel_number", "location"],
}


def main() -> int:
    root = config.data_dir()
    if OUT.exists():
        shutil.rmtree(OUT)

    for rel in FULL_COPIES:
        src = root / rel
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        for sidecar in (src.with_suffix(".manifest.json"),):
            if sidecar.exists():
                shutil.copy2(sidecar, dst.with_suffix(".manifest.json"))
        print(f"  copied  {rel}")

    for rel, cols in TRIMS.items():
        src = root / rel
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        pl.scan_parquet(src).select(cols).collect().write_parquet(dst)
        print(f"  trimmed {rel} -> {len(cols)} cols")

    for kind in ("baseline", "condo"):
        run = latest_run_dir(kind, root)
        dst = OUT / "models" / run.name
        shutil.copytree(run, dst)
        print(f"  copied  models/{run.name}")

    total = subprocess.run(
        ["du", "-sh", str(OUT)], capture_output=True, text=True, check=True
    ).stdout.split()[0]
    print(f"bundle ready: {OUT} ({total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
