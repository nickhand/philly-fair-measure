"""Shared writer for derived (staged/mart) tables: atomic Parquet + provenance manifest."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from philly_fair_measure import __version__
from philly_fair_measure.ingest.manifests import (
    DerivedManifest,
    InputRef,
    write_derived_manifest,
)

logger = logging.getLogger(__name__)


def write_derived_table(
    frame: pl.DataFrame,
    root: Path,
    layer: str,
    table: str,
    inputs: list[InputRef],
    notes: str | None = None,
) -> tuple[Path, DerivedManifest]:
    directory = root / layer
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{table}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    frame.write_parquet(tmp, compression="zstd")
    tmp.rename(path)

    manifest = DerivedManifest(
        layer=layer,
        table=table,
        built_at=datetime.now(UTC),
        row_count=frame.height,
        inputs=inputs,
        package_version=__version__,
        notes=notes,
    )
    write_derived_manifest(manifest, path)
    logger.info("%s/%s: %s rows -> %s", layer, table, f"{frame.height:,}", path)
    return path, manifest
