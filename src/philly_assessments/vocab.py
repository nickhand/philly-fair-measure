"""Controlled vocabularies as enums (Robust Python: make illegal states
unrepresentable).

Every value here is a `StrEnum`, so members ARE their string values — they
serialize into parquet, compare against polars string columns, and print
exactly as before — but the set is now centralized and type-checked. A typo
like ``ValidityStatus.ARMS_LENGHT`` is a definition-time error instead of a
silently non-matching string literal (the specific bug class this replaces:
`pl.col("validity_status") == "arms_lenght"` returns all-False, no error).

Import the member (``ValidityStatus.ARMS_LENGTH``) rather than the bare string
anywhere the value is produced or compared.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

# Persisted model-run directory kinds (data/models/run_id=<stamp>-<kind>).
# A Literal rather than a StrEnum: the values only ever appear as call-site
# literals, where Literal gives static typo-checking with no conversion step.
RunKind = Literal["baseline", "retail", "bayesian", "condo"]


class ValidityStatus(StrEnum):
    """Sale-validity classification (validation/sales.py)."""

    ARMS_LENGTH = "arms_length"
    SUSPECT = "suspect"
    NOMINAL = "nominal"
    NOT_ARMS_LENGTH = "not_arms_length"
    EXCLUDED = "excluded"


class ModelFamily(StrEnum):
    """Which model priced a screen row (validation/opa.py)."""

    RESIDENTIAL = "residential"
    CONDO = "condo"


class AssessmentFlag(StrEnum):
    """Screen disagreement classification (validation/opa.py)."""

    OVER = "over_assessed_candidate"
    UNDER = "under_assessed_candidate"
    WITHIN = "within_range"
    NONE = "no_assessment"


class IntervalMethod(StrEnum):
    """How a screen row's predictive interval was produced."""

    BAYESIAN = "bayesian_posterior"
    CONFORMAL = "conformal_knn"


class Market(StrEnum):
    """Valuation target convention (models/baseline.py)."""

    BLEND = "blend"
    RETAIL = "retail"


class OpaLinkSource(StrEnum):
    """How a deed/mortgage row acquired its OPA account (staging/tables.py)."""

    RTT = "rtt"
    ADDRESS_UNIT = "address_unit"


class TemporalStatus(StrEnum):
    """Per-value parse status of a raw temporal column (staging/temporal.py)."""

    OK = "ok"
    MISSING = "missing"
    INVALID = "invalid"
    IMPLAUSIBLE = "implausible"
