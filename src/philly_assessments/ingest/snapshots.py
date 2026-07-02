"""Capture raw snapshots of source tables as Parquet plus a manifest.

Layout::

    data/raw/source=carto/dataset=<name>/fetched_at=<UTC stamp>/data.parquet
                                                               /manifest.json

Snapshots are immutable once written. The fetch writes into a sibling directory
with an ``.incomplete`` suffix and renames it only after the manifest lands, so
a crashed fetch can never masquerade as a valid snapshot.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from philly_assessments import __version__, config
from philly_assessments.ingest.manifests import (
    ColumnInfo,
    FileInfo,
    SnapshotManifest,
    write_manifest,
)
from philly_assessments.sources.carto import (
    DEFAULT_EXCLUDED_COLUMNS,
    DEFAULT_PAGE_SIZE,
    KEYSET_COLUMN,
    CartoClient,
    arrow_schema,
    rows_to_table,
)

logger = logging.getLogger(__name__)

DATA_FILENAME = "data.parquet"
FETCHED_AT_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class SnapshotResult:
    directory: Path
    manifest: SnapshotManifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_carto_table(
    table: str,
    *,
    dataset: str | None = None,
    data_dir: Path | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    limit: int | None = None,
    exclude_columns: Sequence[str] = DEFAULT_EXCLUDED_COLUMNS,
    client: CartoClient | None = None,
) -> SnapshotResult:
    dataset = dataset or table
    owns_client = client is None
    client = client or CartoClient()
    try:
        fetched_at = datetime.now(UTC)
        started = time.monotonic()

        excluded = set(exclude_columns)
        columns = [c for c in client.get_columns(table) if c.name not in excluded]
        if KEYSET_COLUMN not in {c.name for c in columns}:
            raise ValueError(
                f"table {table!r} has no {KEYSET_COLUMN} column; keyset pagination unavailable"
            )
        schema = arrow_schema(columns)
        source_row_count = client.count_rows(table)

        root = data_dir if data_dir is not None else config.data_dir()
        final_dir = (
            root
            / "raw"
            / "source=carto"
            / f"dataset={dataset}"
            / f"fetched_at={fetched_at.strftime(FETCHED_AT_FORMAT)}"
        )
        work_dir = final_dir.with_name(final_dir.name + ".incomplete")
        work_dir.mkdir(parents=True, exist_ok=False)
        data_path = work_dir / DATA_FILENAME

        row_count = 0
        num_pages = 0
        with pq.ParquetWriter(data_path, schema, compression="zstd") as writer:
            pages = client.iter_pages(
                table,
                columns=[c.name for c in columns],
                page_size=page_size,
                limit=limit,
            )
            for page in pages:
                writer.write_table(rows_to_table(page, schema))
                row_count += len(page)
                num_pages += 1
                if num_pages % 10 == 0:
                    logger.info(
                        "%s: %s rows fetched (%d pages)", dataset, f"{row_count:,}", num_pages
                    )

        completed_at = datetime.now(UTC)
        manifest = SnapshotManifest(
            source="carto",
            dataset=dataset,
            endpoint=client.base_url,
            query=(
                f'SELECT <{len(columns)} columns> FROM "{table}" '
                f'ORDER BY "{KEYSET_COLUMN}" -- keyset pages of {page_size}'
            ),
            fetched_at=fetched_at,
            completed_at=completed_at,
            duration_seconds=round(time.monotonic() - started, 3),
            source_row_count=source_row_count,
            row_count=row_count,
            page_size=page_size,
            num_pages=num_pages,
            order_key=KEYSET_COLUMN,
            row_limit=limit,
            excluded_columns=sorted(excluded),
            columns=[
                ColumnInfo(
                    name=c.name,
                    carto_type=c.carto_type,
                    pg_type=c.pg_type,
                    arrow_type=str(c.arrow_type()),
                )
                for c in columns
            ],
            files=[
                FileInfo(
                    path=DATA_FILENAME,
                    rows=row_count,
                    size_bytes=data_path.stat().st_size,
                    sha256=_sha256(data_path),
                )
            ],
            package_version=__version__,
        )
        write_manifest(manifest, work_dir)
        work_dir.rename(final_dir)
        logger.info("snapshot complete: %s rows -> %s", f"{row_count:,}", final_dir)
        return SnapshotResult(directory=final_dir, manifest=manifest)
    finally:
        if owns_client:
            client.close()
