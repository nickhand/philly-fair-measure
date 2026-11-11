"""Project configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

DEFAULT_DATA_DIR: Final = Path("data")

# OPA accounts beginning with 88 are condominium units (and related condo
# parcels: parking, storage, common elements). They carry building-scale or
# token characteristics under residential category codes, so they are excluded
# from the residential model scope and market-signal pools; condos need a
# dedicated model (see the CCAO condo playbook in docs/ccao-lessons.md).
CONDO_ACCOUNT_PREFIX: Final = "88"

# The recurring snapshot set: `fair-measure snapshot-all` captures every table
# here except the paused ones below. Page sizes reflect row width (verified in
# docs/source_inventory.md).
CORE_CARTO_TABLES: Final[dict[str, int]] = {
    "opa_properties_public": 20_000,
    "assessments": 50_000,
    "rtt_summary": 30_000,
    "permits": 20_000,
    "violations": 20_000,
    "real_estate_tax_delinquencies": 30_000,
    "demolitions": 30_000,
    # L&I distress/tenure family (live-verified 2026-07-03)
    "complaints": 30_000,
    "case_investigations": 30_000,
    "business_licenses": 20_000,
    "appeals": 20_000,
}

# Core tables a default `snapshot-all` skips, with the reason it prints. Naming
# one in `snapshot-all --tables` still fetches it, to check whether access is back.
PAUSED_CARTO_TABLES: Final[dict[str, str]] = {
    "real_estate_tax_delinquencies": (
        "CARTO has denied access since 2026-09-21; see docs/snapshots/README.md"
    ),
}

# The core tables the weekly snapshot job and `just snapshot-current` capture.
# `fair-measure freshness` checks only these, because nothing else refreshes on
# a schedule. .github/ci/test_snapshot_tables.py fails when either list differs.
SCHEDULED_CARTO_TABLES: Final[tuple[str, ...]] = (
    "opa_properties_public",
    "assessments",
    "rtt_summary",
    "permits",
    "violations",
)


def data_dir() -> Path:
    """Root of the local data lake (raw/, staged/, marts/).

    Defaults to ./data; override with the PHILLY_DATA_DIR environment variable.
    """
    return Path(os.environ.get("PHILLY_DATA_DIR", str(DEFAULT_DATA_DIR)))
