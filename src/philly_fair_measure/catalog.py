"""DuckDB catalog over raw Parquet snapshots.

Discovers snapshots under ``data/raw/source=<source>/dataset=<dataset>/
fetched_at=<stamp>/`` and registers one DuckDB view per dataset —
``raw_<dataset>`` — pointing at the *latest* snapshot's Parquet file. Analyses
always read the newest immutable raw data without copying it; pass an older
``SnapshotRef`` explicitly to pin a historical snapshot.

Dataset names are assumed unique across sources (true today; revisit if a
second source ever publishes a colliding name).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from philly_fair_measure import config
from philly_fair_measure.ingest.manifests import (
    MANIFEST_FILENAME,
    DerivedManifest,
    SnapshotManifest,
    read_derived_manifest,
    read_manifest,
)
from philly_fair_measure.ingest.snapshots import DATA_FILENAME

RAW_VIEW_PREFIX = "raw_"
DERIVED_LAYERS = {"staged": "stg_", "marts": "mart_"}
_INCOMPLETE_SUFFIX = ".incomplete"
_MANAGED_VIEW_PREFIXES = (RAW_VIEW_PREFIX, *DERIVED_LAYERS.values())


@dataclass(frozen=True)
class SnapshotRef:
    source: str
    dataset: str
    fetched_at: str
    directory: Path

    @property
    def data_path(self) -> Path:
        return self.directory / DATA_FILENAME

    @property
    def view_name(self) -> str:
        return RAW_VIEW_PREFIX + self.dataset

    def manifest(self) -> SnapshotManifest:
        return read_manifest(self.directory)


def _partition_value(name: str) -> str:
    return name.split("=", 1)[1]


def list_snapshots(data_dir: Path | None = None) -> list[SnapshotRef]:
    """All complete snapshots on disk, sorted by (dataset, fetched_at)."""
    root = (data_dir if data_dir is not None else config.data_dir()) / "raw"
    refs = []
    for snapshot_dir in root.glob("source=*/dataset=*/fetched_at=*"):
        if snapshot_dir.name.endswith(_INCOMPLETE_SUFFIX):
            continue
        if not (snapshot_dir / DATA_FILENAME).exists():
            continue
        if not (snapshot_dir / MANIFEST_FILENAME).exists():
            continue
        refs.append(
            SnapshotRef(
                source=_partition_value(snapshot_dir.parent.parent.name),
                dataset=_partition_value(snapshot_dir.parent.name),
                fetched_at=_partition_value(snapshot_dir.name),
                directory=snapshot_dir,
            )
        )
    return sorted(refs, key=lambda ref: (ref.dataset, ref.fetched_at))


def latest_snapshots(data_dir: Path | None = None) -> dict[str, SnapshotRef]:
    """Latest complete snapshot per dataset, keyed by dataset name.

    The fetched_at stamp (%Y%m%dT%H%M%SZ) sorts lexicographically as UTC time.
    """
    latest: dict[str, SnapshotRef] = {}
    for ref in list_snapshots(data_dir):
        current = latest.get(ref.dataset)
        if current is not None and current.source != ref.source:
            raise ValueError(
                f"dataset {ref.dataset!r} is published by both "
                f"{current.source!r} and {ref.source!r}; raw view names require "
                "dataset names to be unique across sources"
            )
        if current is None or ref.fetched_at > current.fetched_at:
            latest[ref.dataset] = ref
    return latest


@dataclass(frozen=True)
class DerivedRef:
    layer: str
    table: str
    path: Path

    @property
    def view_name(self) -> str:
        return DERIVED_LAYERS[self.layer] + self.table

    def manifest(self) -> DerivedManifest:
        return read_derived_manifest(self.path)


def list_derived(data_dir: Path | None = None) -> list[DerivedRef]:
    """Staged and mart tables on disk, sorted by (layer, table)."""
    root = data_dir if data_dir is not None else config.data_dir()
    refs = []
    for layer in DERIVED_LAYERS:
        for path in sorted((root / layer).glob("*.parquet")):
            refs.append(DerivedRef(layer=layer, table=path.stem, path=path))
    return refs


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    """Return a DuckDB string literal without relying on Python ``repr`` rules."""
    return "'" + value.replace("'", "''") + "'"


def _managed_views(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        """
        SELECT view_name
        FROM duckdb_views()
        WHERE NOT internal
          AND database_name = current_database()
          AND schema_name = current_schema()
        """
    ).fetchall()
    return {str(row[0]) for row in rows if str(row[0]).startswith(_MANAGED_VIEW_PREFIXES)}


def _refresh_views(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path | None,
) -> None:
    """Atomically make catalog-managed views match the files currently on disk.

    View prefixes documented by this module are reserved for generated views.
    Removing stale views matters for persistent databases: otherwise a dataset
    removed from the data lake remains queryable through an obsolete path.
    """
    bindings = {ref.view_name: ref.data_path for ref in latest_snapshots(data_dir).values()}
    bindings.update({ref.view_name: ref.path for ref in list_derived(data_dir)})

    con.execute("BEGIN TRANSACTION")
    try:
        for view_name in sorted(_managed_views(con) - bindings.keys()):
            con.execute(f"DROP VIEW {_quote_identifier(view_name)}")
        for view_name, path in sorted(bindings.items()):
            con.execute(
                f"CREATE OR REPLACE VIEW {_quote_identifier(view_name)} AS "
                f"SELECT * FROM read_parquet({_quote_string(str(path.resolve()))})"
            )
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def connect(data_dir: Path | None = None, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Open DuckDB with views over the data lake.

    raw_<dataset> reads each dataset's latest snapshot; stg_<table> and
    mart_<table> read staged and mart tables.
    """
    con = duckdb.connect(database)
    try:
        _refresh_views(con, data_dir)
    except Exception:
        con.close()
        raise
    return con
