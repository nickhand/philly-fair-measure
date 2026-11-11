"""`just bundle-data` must ship the model runs the screen was built with.

The API serves the screen rows next to drivers and comps scored from the
bundled baseline and condo runs, so a bundle that took the newest runs instead
would explain estimates with a model that did not make them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef, write_derived_manifest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bundle_deploy_data.py"
SCREEN_BASELINE = "20260714T190028Z-baseline"
SCREEN_CONDO = "20260714T194046Z-condo"


def _lake(root: Path, screen_runs: tuple[str, ...] = (SCREEN_BASELINE, SCREEN_CONDO)) -> None:
    tables = {
        "marts/assessment_screen": {"parcel_id": ["1"]},
        "marts/assessment_features": {"parcel_id": ["1"]},
        "marts/condo_assessment_features": {"parcel_id": ["2"]},
        "marts/condo_sale_features": {"parcel_id": ["2"]},
        "marts/sale_features": {"parcel_id": ["1"]},
        "marts/sale_validity": {
            "parcel_id": ["1"],
            "sale_date": [datetime(2024, 1, 1)],
            "sale_price": [100_000.0],
            "deed_kind": ["deed"],
            "validity_status": ["arms_length"],
        },
        "staged/assessments": {
            "parcel_number": ["1"],
            "year_parsed": [2025],
            "market_value": [1.0],
        },
        "staged/opa_properties": {"parcel_number": ["1"], "location": ["1 TEST ST"]},
    }
    for rel, columns in tables.items():
        path = root / f"{rel}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(columns).write_parquet(path)
    write_derived_manifest(
        DerivedManifest(
            layer="marts",
            table="assessment_screen",
            built_at=datetime(2026, 7, 14, 19, 42, tzinfo=UTC),
            row_count=1,
            inputs=[
                InputRef(dataset=f"models/{run}", fetched_at="2026-07-14T19:00:00+00:00")
                for run in (*screen_runs, "20260714T193149Z-bayesian")
            ]
            + [InputRef(dataset="marts/sale_validity", fetched_at="2026-07-10T01:47:12+00:00")],
            package_version="0",
        ),
        root / "marts" / "assessment_screen.parquet",
    )
    for run in (
        SCREEN_BASELINE,
        "20260801T000000Z-baseline",
        SCREEN_CONDO,
        "20260801T000000Z-condo",
    ):
        run_dir = root / "models" / f"run_id={run}"
        run_dir.mkdir(parents=True)
        for name in ("model_lightgbm.txt", "params.json"):
            (run_dir / name).write_text(run)
        if run.endswith("-baseline"):
            for name in ("model_lightgbm_q05.txt", "model_lightgbm_q95.txt"):
                (run_dir / name).write_text(run)


def _bundle(cwd: Path, lake: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        env={**os.environ, "PHILLY_DATA_DIR": str(lake)},
        capture_output=True,
        text=True,
        check=False,
    )


def _previous_bundle(cwd: Path) -> Path:
    sentinel = cwd / "deploy" / "data" / "previous.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("the bundle that was deployed")
    return sentinel


def test_bundles_the_runs_the_screen_names_not_the_newest(tmp_path: Path) -> None:
    _lake(tmp_path / "lake")
    result = _bundle(tmp_path, tmp_path / "lake")
    assert result.returncode == 0, result.stderr

    bundle = tmp_path / "deploy" / "data"
    assert sorted(p.name for p in (bundle / "models").iterdir()) == [
        f"run_id={SCREEN_BASELINE}",
        f"run_id={SCREEN_CONDO}",
    ]
    baseline = bundle / "models" / f"run_id={SCREEN_BASELINE}"
    assert sorted(p.name for p in baseline.iterdir()) == ["model_lightgbm.txt", "params.json"]
    assert (bundle / "marts" / "assessment_screen.manifest.json").exists()
    assert pl.read_parquet(bundle / "staged" / "opa_properties.parquet").columns == [
        "parcel_number",
        "location",
    ]


def test_keeps_the_previous_bundle_when_a_source_is_missing(tmp_path: Path) -> None:
    _lake(tmp_path / "lake")
    (tmp_path / "lake" / "staged" / "assessments.parquet").unlink()
    sentinel = _previous_bundle(tmp_path)

    result = _bundle(tmp_path, tmp_path / "lake")

    assert result.returncode != 0
    assert sentinel.read_text() == "the bundle that was deployed"
    assert sorted(p.name for p in (tmp_path / "deploy" / "data").iterdir()) == ["previous.txt"]


def test_refuses_a_screen_that_names_no_condo_run(tmp_path: Path) -> None:
    _lake(tmp_path / "lake", screen_runs=(SCREEN_BASELINE,))
    sentinel = _previous_bundle(tmp_path)

    result = _bundle(tmp_path, tmp_path / "lake")

    assert result.returncode != 0
    assert "condo" in result.stderr
    assert sentinel.read_text() == "the bundle that was deployed"
