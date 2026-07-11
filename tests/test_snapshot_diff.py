"""snapshot-diff: null-safe change counts, key add/remove, dedup keep-last,
dataset notes (homestead adds, past-year restatements), and the markdown."""

from pathlib import Path

import polars as pl

from philly_fair_measure.ingest.diff import (
    SNAPSHOT_DIFF_SPECS,
    DiffSpec,
    diff_dataset,
    render_markdown,
)


def _write(path: Path, df: pl.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return path


def _diff(tmp_path: Path, prev: pl.DataFrame, new: pl.DataFrame, spec: DiffSpec, dataset: str):
    return diff_dataset(
        _write(tmp_path / "prev.parquet", prev),
        _write(tmp_path / "new.parquet", new),
        spec,
        dataset=dataset,
        prev_stamp="20260701T000000Z",
        new_stamp="20260801T000000Z",
    )


SPEC = DiffSpec(keys=("parcel_number",), watched=("market_value", "quality_grade"))


def test_added_removed_and_changed(tmp_path: Path) -> None:
    prev = pl.DataFrame(
        {
            "parcel_number": ["1", "2", "3"],
            "market_value": [100, 200, 300],
            "quality_grade": ["C", "C", "C"],
        }
    )
    new = pl.DataFrame(
        {
            "parcel_number": ["2", "3", "4"],  # 1 removed, 4 added
            "market_value": [250, 300, 400],  # 2 changed
            "quality_grade": ["C", "B", "C"],  # 3 changed
        }
    )
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    assert (d.n_prev, d.n_new, d.n_added, d.n_removed) == (3, 3, 1, 1)
    assert d.n_changed_rows == 2  # parcels 2 and 3
    by_col = {c.column: c for c in d.columns}
    assert by_col["market_value"].n_changed == 1
    assert by_col["market_value"].median_delta == 50.0
    assert by_col["quality_grade"].n_changed == 1
    assert by_col["quality_grade"].median_delta is None  # non-numeric


def test_null_safe_comparison(tmp_path: Path) -> None:
    prev = pl.DataFrame(
        {
            "parcel_number": ["1", "2", "3"],
            "market_value": [None, None, 300],
            "quality_grade": ["C", "C", "C"],
        }
    )
    new = pl.DataFrame(
        {
            "parcel_number": ["1", "2", "3"],
            "market_value": [None, 200, None],  # null->null: no; null->200: yes; 300->null: yes
            "quality_grade": ["C", "C", "C"],
        }
    )
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    by_col = {c.column: c for c in d.columns}
    assert by_col["market_value"].n_changed == 2
    assert d.n_changed_rows == 2


def test_duplicate_keys_keep_last(tmp_path: Path) -> None:
    prev = pl.DataFrame(
        {
            "parcel_number": ["1", "1"],
            "market_value": [100, 150],  # keep-last -> 150
            "quality_grade": ["C", "C"],
        }
    )
    new = pl.DataFrame({"parcel_number": ["1"], "market_value": [150], "quality_grade": ["C"]})
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    assert d.n_prev == 1
    assert d.n_changed_rows == 0


def test_missing_watched_column_is_noted_not_fatal(tmp_path: Path) -> None:
    prev = pl.DataFrame({"parcel_number": ["1"], "market_value": [100]})
    new = pl.DataFrame({"parcel_number": ["1"], "market_value": [100]})
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    assert {c.column for c in d.columns} == {"market_value"}
    assert not any("quality_grade" in n for n in d.notes)  # absent in BOTH: silently ignored


def test_schema_drift_is_noted(tmp_path: Path) -> None:
    prev = pl.DataFrame({"parcel_number": ["1"], "market_value": [100]})
    new = pl.DataFrame({"parcel_number": ["1"], "market_value": [100], "quality_grade": ["C"]})
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    assert any("quality_grade" in n and "skipped" in n for n in d.notes)


def test_homestead_note(tmp_path: Path) -> None:
    spec = DiffSpec(keys=("parcel_number",), watched=("homestead_exemption",))
    prev = pl.DataFrame(
        {"parcel_number": ["1", "2", "3"], "homestead_exemption": [0, 100_000, None]}
    )
    new = pl.DataFrame(
        {"parcel_number": ["1", "2", "3"], "homestead_exemption": [100_000, 0, 100_000]}
    )
    d = _diff(tmp_path, prev, new, spec, "opa_properties_public")
    assert "homestead exemption: 2 added, 1 removed" in d.notes


def test_assessments_restatement_note_and_compound_key(tmp_path: Path) -> None:
    spec = SNAPSHOT_DIFF_SPECS["assessments"]
    prev = pl.DataFrame(
        {
            "parcel_number": ["1", "1", "2"],
            "year": ["2025", "2027", "2027"],
            "market_value": [100, 120, 200],
            "taxable_building": [0, 0, 0],
            "taxable_land": [0, 0, 0],
            "exempt_building": [0, 0, 0],
            "exempt_land": [0, 0, 0],
        }
    )
    new = prev.with_columns(
        market_value=pl.Series([90, 120, 210])  # 2025 restated for parcel 1; 2027 for parcel 2
    )
    d = _diff(tmp_path, prev, new, spec, "assessments")
    assert d.n_changed_rows == 2
    note = next(n for n in d.notes if n.startswith("market_value changed by assessment year"))
    assert "2025: 1" in note
    assert "2027: 1" in note


def test_sheriff_sale_note(tmp_path: Path) -> None:
    spec = DiffSpec(keys=("opa_number",), watched=("sheriff_sale",))
    prev = pl.DataFrame({"opa_number": ["1", "2"], "sheriff_sale": ["N", "Y"]})
    new = pl.DataFrame({"opa_number": ["1", "2"], "sheriff_sale": ["Y", "N"]})
    d = _diff(tmp_path, prev, new, spec, "real_estate_tax_delinquencies")
    assert "sheriff sale flag newly set on 1 accounts" in d.notes


def test_markdown_renders_counts_and_notes(tmp_path: Path) -> None:
    prev = pl.DataFrame(
        {"parcel_number": ["1", "2"], "market_value": [100, 200], "quality_grade": ["C", "C"]}
    )
    new = pl.DataFrame(
        {"parcel_number": ["1", "2"], "market_value": [100, 260], "quality_grade": ["C", "C"]}
    )
    d = _diff(tmp_path, prev, new, SPEC, "opa_properties_public")
    md = render_markdown([d], generated_at="2026-08-01")
    assert "# Snapshot diff, 2026-08-01" in md
    assert "## opa_properties_public" in md
    assert "| market_value | 1 | +60 |" in md
    assert "`20260701T000000Z` -> `20260801T000000Z`" in md


def test_specs_cover_the_current_only_tables() -> None:
    assert set(SNAPSHOT_DIFF_SPECS) == {
        "opa_properties_public",
        "assessments",
        "real_estate_tax_delinquencies",
    }
