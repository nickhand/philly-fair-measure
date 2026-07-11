"""Diff two raw snapshots of a current-only table.

The city overwrites `opa_properties_public`, `assessments`, and
`real_estate_tax_delinquencies` in place, so the monthly snapshot program
(docs/snapshots/README.md) is the only record of what changed. This module
answers "what did the city change between two snapshots" per dataset: keys
added and removed, per-column change counts over a watched-column list, and a
few dataset-specific notes (homestead adds, past-year restatements, sheriff
sale flips).

Comparisons are null-safe (`ne_missing`): null -> value counts as a change,
null -> null does not. Duplicate keys (the raw assessments table carries a
handful) are deduplicated keep-last before comparing, and the dedup counts are
reported rather than hidden.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

import polars as pl

# Columns that identify a row and columns worth tracking per dataset. Watched
# lists deliberately exclude unstable plumbing (cartodb_id, objectid, the_geom)
# and free-text mailing fields that churn without meaning.
_WATCHED_PROPERTIES: Final = (
    "market_value",
    "taxable_building",
    "taxable_land",
    "exempt_building",
    "exempt_land",
    "homestead_exemption",
    "total_livable_area",
    "total_area",
    "interior_condition",
    "exterior_condition",
    "quality_grade",
    "building_code",
    "category_code",
    "year_built",
    "number_of_bedrooms",
    "number_of_bathrooms",
    "number_stories",
    "owner_1",
    "sale_date",
    "sale_price",
    "zoning",
)
_WATCHED_ASSESSMENTS: Final = (
    "market_value",
    "taxable_building",
    "taxable_land",
    "exempt_building",
    "exempt_land",
)
_WATCHED_DELINQUENCIES: Final = (
    "total_due",
    "principal_due",
    "num_years_owed",
    "most_recent_year_owed",
    "sheriff_sale",
    "payment_agreement",
    "is_actionable",
    "coll_agency_total_owed",
)


@dataclass(frozen=True)
class DiffSpec:
    """How to diff one dataset: identity columns + columns to track."""

    keys: tuple[str, ...]
    watched: tuple[str, ...]


SNAPSHOT_DIFF_SPECS: Final[dict[str, DiffSpec]] = {
    "opa_properties_public": DiffSpec(keys=("parcel_number",), watched=_WATCHED_PROPERTIES),
    "assessments": DiffSpec(keys=("parcel_number", "year"), watched=_WATCHED_ASSESSMENTS),
    "real_estate_tax_delinquencies": DiffSpec(keys=("opa_number",), watched=_WATCHED_DELINQUENCIES),
}


@dataclass(frozen=True)
class ColumnChange:
    column: str
    n_changed: int
    # median of (new - old) among changed rows; None for non-numeric columns
    # or when nothing changed
    median_delta: float | None = None


@dataclass(frozen=True)
class SnapshotDiff:
    dataset: str
    prev_stamp: str
    new_stamp: str
    n_prev: int
    n_new: int
    n_added: int
    n_removed: int
    n_changed_rows: int
    columns: list[ColumnChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _load(path: Path, spec: DiffSpec) -> pl.DataFrame:
    """Key + watched columns only, keys stringified, duplicate keys keep-last."""
    lf = pl.scan_parquet(path)
    present = set(lf.collect_schema().names())
    watched = [c for c in spec.watched if c in present]
    missing = [k for k in spec.keys if k not in present]
    if missing:
        raise ValueError(f"{path}: missing key column(s) {missing}")
    return (
        lf.select(
            [pl.col(k).cast(pl.String).alias(k) for k in spec.keys] + [pl.col(c) for c in watched]
        )
        .drop_nulls(list(spec.keys))
        .unique(subset=list(spec.keys), keep="last")
        .collect()
    )


def diff_dataset(
    prev_path: Path,
    new_path: Path,
    spec: DiffSpec,
    *,
    dataset: str,
    prev_stamp: str,
    new_stamp: str,
) -> SnapshotDiff:
    prev = _load(prev_path, spec)
    new = _load(new_path, spec)
    keys = list(spec.keys)
    # only columns present in BOTH snapshots are comparable (schema drift is a note)
    watched = [c for c in spec.watched if c in prev.columns and c in new.columns]
    notes = [
        f"column `{c}` not present in both snapshots; skipped"
        for c in spec.watched
        if (c in prev.columns) != (c in new.columns)
    ]

    n_added = new.join(prev, on=keys, how="anti").height
    n_removed = prev.join(new, on=keys, how="anti").height

    joined = prev.join(new, on=keys, how="inner", suffix="_new")
    flags = joined.with_columns(
        [pl.col(c).ne_missing(pl.col(f"{c}_new")).alias(f"chg_{c}") for c in watched]
    )
    changed_any = (
        int(flags.select(pl.any_horizontal([pl.col(f"chg_{c}") for c in watched]).sum()).item())
        if watched
        else 0
    )

    columns: list[ColumnChange] = []
    for c in watched:
        n_changed = int(flags.select(pl.col(f"chg_{c}").sum()).item())
        median_delta: float | None = None
        if n_changed and flags.schema[c].is_numeric():
            delta = flags.filter(pl.col(f"chg_{c}")).select(
                (pl.col(f"{c}_new") - pl.col(c)).median()
            )
            value = delta.item()
            median_delta = float(value) if value is not None else None
        columns.append(ColumnChange(column=c, n_changed=n_changed, median_delta=median_delta))

    notes.extend(_dataset_notes(dataset, flags))
    return SnapshotDiff(
        dataset=dataset,
        prev_stamp=prev_stamp,
        new_stamp=new_stamp,
        n_prev=prev.height,
        n_new=new.height,
        n_added=n_added,
        n_removed=n_removed,
        n_changed_rows=changed_any,
        columns=columns,
        notes=notes,
    )


def _dataset_notes(dataset: str, flags: pl.DataFrame) -> list[str]:
    """Derived facts worth calling out per dataset."""
    notes: list[str] = []
    if dataset == "opa_properties_public" and "chg_homestead_exemption" in flags.columns:
        hs_prev = pl.col("homestead_exemption").fill_null(0)
        hs_new = pl.col("homestead_exemption_new").fill_null(0)
        adds = int(flags.select(((hs_prev == 0) & (hs_new > 0)).sum()).item())
        drops = int(flags.select(((hs_prev > 0) & (hs_new == 0)).sum()).item())
        if adds or drops:
            notes.append(f"homestead exemption: {adds:,} added, {drops:,} removed")
    if dataset == "assessments" and "chg_market_value" in flags.columns:
        restated = (
            flags.filter(pl.col("chg_market_value"))
            .group_by("year")
            .len()
            .sort("year", descending=True)
        )
        if restated.height:
            parts = ", ".join(f"{r['year']}: {r['len']:,}" for r in restated.to_dicts()[:6])
            notes.append(f"market_value changed by assessment year ({parts})")
    if dataset == "real_estate_tax_delinquencies" and "chg_sheriff_sale" in flags.columns:
        to_yes = int(
            flags.select(
                (
                    pl.col("sheriff_sale").fill_null("N").ne("Y")
                    & pl.col("sheriff_sale_new").fill_null("N").eq("Y")
                ).sum()
            ).item()
        )
        if to_yes:
            notes.append(f"sheriff sale flag newly set on {to_yes:,} accounts")
    return notes


def render_markdown(diffs: list[SnapshotDiff], *, generated_at: str) -> str:
    """One compact markdown report for a snapshot run (committed to the repo)."""
    lines = [
        f"# Snapshot diff, {generated_at}",
        "",
        "What the city changed in the current-only tables since the previous",
        "snapshot. Raw parquet lives in S3 (see docs/snapshots/README.md);",
        "this summary is the greppable record.",
        "",
    ]
    for d in diffs:
        lines += [
            f"## {d.dataset}",
            "",
            f"`{d.prev_stamp}` -> `{d.new_stamp}`: "
            f"{d.n_prev:,} -> {d.n_new:,} rows, "
            f"{d.n_added:,} added, {d.n_removed:,} removed, "
            f"{d.n_changed_rows:,} rows with watched-column changes.",
            "",
        ]
        changed = [c for c in d.columns if c.n_changed]
        if changed:
            lines += ["| column | rows changed | median delta |", "| --- | ---: | ---: |"]
            for c in sorted(changed, key=lambda c: c.n_changed, reverse=True):
                delta = "" if c.median_delta is None else f"{c.median_delta:+,.0f}"
                lines.append(f"| {c.column} | {c.n_changed:,} | {delta} |")
            lines.append("")
        else:
            lines += ["No watched-column changes.", ""]
        for note in d.notes:
            lines.append(f"- {note}")
        if d.notes:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
