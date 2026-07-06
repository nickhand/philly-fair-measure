"""Screen audit: the pathology review as a permanent, repeatable gate.

Two layers:

- ``assert_screen_invariants`` — structural truths of the screen that code
  changes must never break: no flag the second uncertainty machine disputes,
  and no display band that excludes its own median. ``build_assessment_screen``
  calls this on every build and refuses to write a mart that violates them
  (these are exactly the two bug classes found in the 2026-07-06 review).

- ``audit_screen`` / ``run_screen_audit`` — the wider health report: flag and
  watch counts, band-width quantiles per family, extreme-value tallies. The
  CLI (`fair-measure screen-audit`) prints it and diffs against the snapshot
  from the previous run (``marts/assessment_screen_audit.json``), so a retrain
  that moves the distribution shows up as a delta, not an anecdote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from philly_fair_measure import config
from philly_fair_measure.vocab import AssessmentFlag

AUDIT_NAME = "assessment_screen_audit.json"
_FLAGGED = [str(AssessmentFlag.OVER), str(AssessmentFlag.UNDER)]


class ScreenInvariantError(RuntimeError):
    """A structural invariant of the assessment screen was violated."""


def _has_conformal(df: pl.DataFrame) -> bool:
    return {"conformal_pi_low_90", "conformal_pi_high_90"}.issubset(df.columns)


def disputed_flag_count(df: pl.DataFrame) -> int:
    """Flags the conformal band disagrees with (must be zero: the agreement
    gate in finalize_screen makes a disputed flag structurally impossible)."""
    if not _has_conformal(df):
        return 0
    return df.filter(
        (
            (pl.col("assessment_flag") == AssessmentFlag.OVER)
            & pl.col("conformal_pi_high_90").is_not_null()
            & (pl.col("opa_market_value") <= pl.col("conformal_pi_high_90"))
        )
        | (
            (pl.col("assessment_flag") == AssessmentFlag.UNDER)
            & pl.col("conformal_pi_low_90").is_not_null()
            & (pl.col("opa_market_value") >= pl.col("conformal_pi_low_90"))
        )
    ).height


def _shown_estimate(df: pl.DataFrame) -> pl.Expr:
    """The estimate surfaces display (display_median since the Stage 5 role
    separation; model_median on older marts/fixtures)."""
    return pl.col("display_median" if "display_median" in df.columns else "model_median")


def incoherent_display_count(df: pl.DataFrame) -> int:
    """Rows whose displayed estimate falls outside their displayed range."""
    if not {"display_pi_low_90", "display_pi_high_90"}.issubset(df.columns):
        return 0
    est = _shown_estimate(df)
    return df.filter(
        est.is_not_null()
        & pl.col("display_pi_low_90").is_not_null()
        & ((est < pl.col("display_pi_low_90")) | (est > pl.col("display_pi_high_90")))
    ).height


def assert_screen_invariants(df: pl.DataFrame) -> None:
    disputed = disputed_flag_count(df)
    incoherent = incoherent_display_count(df)
    pinned = audit_screen(df)["invariants"]["median_pinned_to_display_edge"]
    if disputed or incoherent or pinned:
        raise ScreenInvariantError(
            f"screen invariants violated: {disputed} flags disputed by the conformal band, "
            f"{incoherent} rows with the median outside the display band, "
            f"{pinned} rows with the estimate pinned to a display edge. "
            "Refusing to write the mart — see validation/screen_audit.py."
        )


def _band_quantiles(df: pl.DataFrame, lo: str, hi: str) -> dict[str, float] | None:
    f = df.filter(pl.col(lo).is_not_null() & (pl.col(lo) > 0))
    if not f.height:
        return None
    stats = f.select(
        (pl.col(hi) / pl.col(lo)).median().alias("median"),
        (pl.col(hi) / pl.col(lo)).quantile(0.99).alias("p99"),
        (pl.col(hi) / pl.col(lo)).max().alias("max"),
    ).to_dicts()[0]
    return {key: round(float(value), 2) for key, value in stats.items() if value is not None}


def audit_screen(df: pl.DataFrame) -> dict[str, Any]:
    flags = {
        f"{row['model_family']}/{row['assessment_flag']}": row["len"]
        for row in df.group_by("model_family", "assessment_flag").agg(pl.len()).to_dicts()
    }
    bands: dict[str, Any] = {}
    for family in sorted(df["model_family"].drop_nulls().unique().to_list()):
        fam = df.filter(pl.col("model_family") == family)
        bands[family] = {
            "display": _band_quantiles(fam, "display_pi_low_90", "display_pi_high_90"),
            "model": _band_quantiles(fam, "model_pi_low_90", "model_pi_high_90"),
        }
    flagged = df.filter(pl.col("assessment_flag").is_in(_FLAGGED))
    low = df.filter(
        (pl.col("assessment_flag") != AssessmentFlag.INSUFFICIENT)
        & (pl.col("model_median") < 30_000)
    )
    # estimate pinned to a display edge (within 0.5%): "estimate $X, range
    # $X–$Y" — the presentation bug the headroom clamp exists to prevent
    est = _shown_estimate(df)
    pinned = df.filter(
        est.is_not_null()
        & (pl.col("display_pi_low_90") > 0)
        & (
            ((est / pl.col("display_pi_low_90")) < 1.005)
            | ((pl.col("display_pi_high_90") / est) < 1.005)
        )
    ).height
    return {
        "rows": df.height,
        "flags": dict(sorted(flags.items())),
        "watch": df.filter(pl.col("attention").is_not_null()).height
        if "attention" in df.columns
        else 0,
        "invariants": {
            "disputed_flags": disputed_flag_count(df),
            "median_outside_display": incoherent_display_count(df),
            "median_pinned_to_display_edge": pinned,
        },
        "bands": bands,
        "extremes": {
            "median_lt_30k": low.height,
            "median_lt_30k_flagged": low.filter(pl.col("assessment_flag").is_in(_FLAGGED)).height,
            "median_gt_5m": df.filter(pl.col("model_median") > 5_000_000).height,
            "flagged_total": flagged.height,
            "opa_missing": df.filter(
                pl.col("opa_market_value").is_null() | (pl.col("opa_market_value") <= 0)
            ).height,
        },
    }


def _flatten(prefix: str, obj: Any, out: dict[str, Any]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), value, out)
    else:
        out[prefix] = obj


def run_screen_audit(data_dir: Path | None = None, *, save: bool = True) -> dict[str, Any]:
    """Audit the current screen mart; return the report plus deltas against
    the previous saved snapshot, then (optionally) save this one in its place."""
    root = data_dir if data_dir is not None else config.data_dir()
    screen = pl.read_parquet(root / "marts" / "assessment_screen.parquet")
    report = audit_screen(screen)
    audit_path = root / "marts" / AUDIT_NAME
    deltas: dict[str, tuple[Any, Any]] = {}
    if audit_path.exists():
        previous = json.loads(audit_path.read_text())
        flat_prev: dict[str, Any] = {}
        flat_now: dict[str, Any] = {}
        _flatten("", previous, flat_prev)
        _flatten("", report, flat_now)
        deltas = {
            key: (flat_prev.get(key), value)
            for key, value in flat_now.items()
            if key in flat_prev and flat_prev[key] != value
        }
    if save:
        audit_path.write_text(json.dumps(report, indent=1, sort_keys=True))
    report["deltas_vs_previous"] = deltas
    return report
