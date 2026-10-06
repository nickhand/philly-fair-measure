from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from philly_fair_measure import catalog
from philly_fair_measure.ingest.manifests import (
    ColumnInfo,
    FileInfo,
    SnapshotManifest,
    write_manifest,
)


def _write_snapshot(
    data_dir: Path,
    dataset: str,
    fetched_at: str,
    rows: dict[str, list] | pa.Table,
    *,
    source: str = "carto",
) -> Path:
    directory = (
        data_dir / "raw" / f"source={source}" / f"dataset={dataset}" / f"fetched_at={fetched_at}"
    )
    directory.mkdir(parents=True)
    table = rows if isinstance(rows, pa.Table) else pa.table(rows)
    pq.write_table(table, directory / "data.parquet")
    now = datetime.now(UTC)
    manifest = SnapshotManifest(
        source=source,
        dataset=dataset,
        endpoint="https://example.test/sql",
        query="SELECT ...",
        fetched_at=now,
        completed_at=now,
        duration_seconds=0.0,
        source_row_count=table.num_rows,
        row_count=table.num_rows,
        page_size=100,
        num_pages=1,
        order_key="cartodb_id",
        columns=[ColumnInfo(name=field.name, arrow_type=str(field.type)) for field in table.schema],
        files=[FileInfo(path="data.parquet", rows=table.num_rows, size_bytes=1, sha256="x")],
        package_version="test",
    )
    write_manifest(manifest, directory)
    return directory


def _populate(tmp_path: Path) -> None:
    _write_snapshot(
        tmp_path, "alpha", "20260101T000000Z", {"parcel_number": ["1"], "value": ["old"]}
    )
    _write_snapshot(
        tmp_path,
        "alpha",
        "20260301T000000Z",
        {"parcel_number": ["1", "2"], "value": ["new", "new"]},
    )
    _write_snapshot(
        tmp_path, "beta", "20260201T000000Z", {"parcel_number": ["2"], "year": ["2026"]}
    )
    # an in-flight fetch and a bare directory must both be ignored
    incomplete = (
        tmp_path
        / "raw"
        / "source=carto"
        / "dataset=alpha"
        / "fetched_at=20260401T000000Z.incomplete"
    )
    incomplete.mkdir(parents=True)
    empty = tmp_path / "raw" / "source=carto" / "dataset=gamma" / "fetched_at=20260101T000000Z"
    empty.mkdir(parents=True)


def test_list_snapshots_finds_only_complete_snapshots(tmp_path):
    _populate(tmp_path)
    refs = catalog.list_snapshots(tmp_path)
    assert [(r.dataset, r.fetched_at) for r in refs] == [
        ("alpha", "20260101T000000Z"),
        ("alpha", "20260301T000000Z"),
        ("beta", "20260201T000000Z"),
    ]
    assert all(r.source == "carto" for r in refs)


def test_latest_snapshots_picks_newest_per_dataset(tmp_path):
    _populate(tmp_path)
    latest = catalog.latest_snapshots(tmp_path)
    assert set(latest) == {"alpha", "beta"}
    assert latest["alpha"].fetched_at == "20260301T000000Z"
    assert latest["alpha"].manifest().row_count == 2


def test_connect_registers_views_over_latest_snapshots(tmp_path):
    _populate(tmp_path)
    con = catalog.connect(tmp_path)
    assert con.sql("SELECT value FROM raw_alpha WHERE parcel_number = '1'").fetchone() == ("new",)
    joined = con.sql(
        """
        SELECT a.parcel_number, b.year
        FROM raw_alpha a
        JOIN raw_beta b USING (parcel_number)
        """
    ).fetchall()
    assert joined == [("2", "2026")]


def test_connect_with_no_snapshots_yields_no_views(tmp_path):
    con = catalog.connect(tmp_path)
    assert con.sql("SELECT count(*) FROM duckdb_views() WHERE NOT internal").fetchone() == (0,)


def test_connect_registers_declared_empty_snapshot(tmp_path):
    empty = pa.table({"MatterRequesterName": pa.array([], type=pa.string())})
    _write_snapshot(tmp_path, "legistar_matter_requesters", "20260301T000000Z", empty)

    con = catalog.connect(tmp_path)

    assert con.sql("SELECT count(*) FROM raw_legistar_matter_requesters").fetchone() == (0,)
    assert con.sql("DESCRIBE raw_legistar_matter_requesters").fetchall()[0][:2] == (
        "MatterRequesterName",
        "VARCHAR",
    )


def test_persistent_connect_removes_stale_managed_views(tmp_path):
    first_data_dir = tmp_path / "first"
    second_data_dir = tmp_path / "second"
    database = tmp_path / "catalog.duckdb"
    _populate(first_data_dir)
    _write_snapshot(
        second_data_dir,
        "delta",
        "20260301T000000Z",
        {"id": [1]},
    )

    catalog.connect(first_data_dir, database=str(database)).close()
    con = catalog.connect(second_data_dir, database=str(database))

    view_names = {
        row[0]
        for row in con.sql("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()
    }
    assert "raw_delta" in view_names
    assert "raw_alpha" not in view_names
    assert "raw_beta" not in view_names


def test_persistent_refresh_is_atomic_when_new_parquet_is_invalid(tmp_path):
    database = tmp_path / "catalog.duckdb"
    _write_snapshot(
        tmp_path,
        "alpha",
        "20260101T000000Z",
        {"value": ["old"]},
    )
    catalog.connect(tmp_path, database=str(database)).close()
    invalid = _write_snapshot(
        tmp_path,
        "alpha",
        "20260201T000000Z",
        {"value": ["new"]},
    )
    (invalid / "data.parquet").write_bytes(b"not a parquet file")

    with pytest.raises(duckdb.Error):
        catalog.connect(tmp_path, database=str(database))

    con = duckdb.connect(str(database), read_only=True)
    assert con.sql("SELECT value FROM raw_alpha").fetchone() == ("old",)


def test_connect_quotes_apostrophe_in_snapshot_path(tmp_path):
    data_dir = tmp_path / "O'Brien"
    _write_snapshot(data_dir, "alpha", "20260101T000000Z", {"value": ["ok"]})

    con = catalog.connect(data_dir)

    assert con.sql("SELECT value FROM raw_alpha").fetchone() == ("ok",)


def test_latest_snapshots_rejects_dataset_name_collision_across_sources(tmp_path):
    _write_snapshot(tmp_path, "alpha", "20260101T000000Z", {"value": ["carto"]})
    _write_snapshot(
        tmp_path,
        "alpha",
        "20260201T000000Z",
        {"value": ["legistar"]},
        source="legistar",
    )

    with pytest.raises(ValueError, match="published by both"):
        catalog.latest_snapshots(tmp_path)
