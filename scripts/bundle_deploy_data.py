"""Assemble the minimal data bundle the API needs at serve time.

Writes deploy/data/ (gitignored) for the Docker build. Everything the API
reads per request is included; the two large history tables are trimmed to
the columns the endpoints actually touch. The baseline and condo runs are the
ones the screen manifest names, so drivers and comps come from the models that
built the screen. Run `just api-smoke` afterwards to boot the API against the
bundle and exercise every endpoint before deploying.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from philly_fair_measure import config  # noqa: E402
from philly_fair_measure.ingest.manifests import read_derived_manifest  # noqa: E402

OUT = Path("deploy/data")
SCREEN = "marts/assessment_screen.parquet"

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

# the CQR quantile heads (~37 MB): the screen build reads them, the API never does
RUN_EXCLUDES = ("model_lightgbm_q05.txt", "model_lightgbm_q95.txt")


def screen_runs(root: Path) -> list[Path]:
    """The baseline and condo runs the screen was built with, from its manifest."""
    runs: dict[str, Path] = {}
    for ref in read_derived_manifest(root / SCREEN).inputs:
        layer, _, run_id = ref.dataset.partition("/")
        kind = run_id.split("-", 1)[-1]
        if layer == "models" and kind in ("baseline", "condo"):
            runs[kind] = root / "models" / f"run_id={run_id}"
    missing = {"baseline", "condo"} - runs.keys()
    if missing:
        raise SystemExit(f"{root / SCREEN} names no {' or '.join(sorted(missing))} run")
    return [runs["baseline"], runs["condo"]]


def build(root: Path, runs: list[Path], out: Path) -> None:
    for rel in FULL_COPIES:
        src = root / rel
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        for sidecar in (src.with_suffix(".manifest.json"),):
            if sidecar.exists():
                shutil.copy2(sidecar, dst.with_suffix(".manifest.json"))
        print(f"  copied  {rel}")

    for rel, cols in TRIMS.items():
        src = root / rel
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        pl.scan_parquet(src).select(cols).collect().write_parquet(dst)
        print(f"  trimmed {rel} -> {len(cols)} cols")

    for run in runs:
        shutil.copytree(
            run, out / "models" / run.name, ignore=shutil.ignore_patterns(*RUN_EXCLUDES)
        )
        print(f"  copied  models/{run.name}")


def main() -> int:
    root = config.data_dir()
    runs = screen_runs(root)
    # build beside the live bundle and swap only after every source is copied, so
    # a missing source leaves the previous bundle in place
    staging = OUT.with_name(f"{OUT.name}.next")
    if staging.exists():
        shutil.rmtree(staging)
    build(root, runs, staging)
    if OUT.exists():
        shutil.rmtree(OUT)
    staging.rename(OUT)

    total = subprocess.run(
        ["du", "-sh", str(OUT)], capture_output=True, text=True, check=True
    ).stdout.split()[0]
    print(f"bundle ready: {OUT} ({total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
