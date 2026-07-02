"""Snapshot manifest schema: fetch provenance recorded alongside every raw snapshot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

MANIFEST_FILENAME = "manifest.json"


class ColumnInfo(BaseModel):
    name: str
    carto_type: str | None = None
    pg_type: str | None = None
    arrow_type: str


class FileInfo(BaseModel):
    path: str
    rows: int
    size_bytes: int
    sha256: str


class SnapshotManifest(BaseModel):
    manifest_version: int = 1
    source: str
    dataset: str
    endpoint: str
    query: str
    fetched_at: datetime
    completed_at: datetime
    duration_seconds: float
    source_row_count: int | None
    row_count: int
    page_size: int
    num_pages: int
    order_key: str | None
    row_limit: int | None = None
    excluded_columns: list[str] = Field(default_factory=list)
    columns: list[ColumnInfo]
    files: list[FileInfo]
    package_version: str
    notes: str | None = None


def write_manifest(manifest: SnapshotManifest, directory: Path) -> Path:
    path = directory / MANIFEST_FILENAME
    path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return path


def read_manifest(directory: Path) -> SnapshotManifest:
    path = directory / MANIFEST_FILENAME
    return SnapshotManifest.model_validate_json(path.read_text())
