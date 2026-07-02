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

from philly_assessments import config
from philly_assessments.ingest.manifests import MANIFEST_FILENAME, SnapshotManifest, read_manifest
from philly_assessments.ingest.snapshots import DATA_FILENAME

RAW_VIEW_PREFIX = "raw_"
_INCOMPLETE_SUFFIX = ".incomplete"


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
        if current is None or ref.fetched_at > current.fetched_at:
            latest[ref.dataset] = ref
    return latest


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect(
    data_dir: Path | None = None, database: str = ":memory:"
) -> duckdb.DuckDBPyConnection:
    """Open DuckDB with a raw_<dataset> view over each dataset's latest snapshot."""
    con = duckdb.connect(database)
    for ref in latest_snapshots(data_dir).values():
        con.execute(
            f"CREATE OR REPLACE VIEW {_quote_identifier(ref.view_name)} AS "
            f"SELECT * FROM read_parquet({str(ref.data_path)!r})"
        )
    return con
