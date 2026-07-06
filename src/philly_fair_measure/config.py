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

# The recurring snapshot set: every table here is captured by `fair-measure snapshot-all`.
# Page sizes reflect row width (verified in docs/source_inventory.md).
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


def data_dir() -> Path:
    """Root of the local data lake (raw/, staged/, marts/).

    Defaults to ./data; override with the PHILLY_DATA_DIR environment variable.
    """
    return Path(os.environ.get("PHILLY_DATA_DIR", str(DEFAULT_DATA_DIR)))
