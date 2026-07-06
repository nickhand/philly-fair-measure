"""Staged layer: typed, deduplicated, classified tables derived from raw snapshots.

Raw snapshots are immutable and API-faithful; staged tables are reproducible
functions of the latest raw snapshots. Every parsed value keeps its raw column
plus a per-value status (ok / missing / invalid / implausible), per the
project's missingness contract.
"""

from philly_fair_measure.staging.runner import build_all

__all__ = ["build_all"]
