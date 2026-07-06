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


class InputRef(BaseModel):
    """A pointer to the exact upstream data a derived table was built from."""

    dataset: str
    fetched_at: str


class DerivedManifest(BaseModel):
    """Provenance sidecar for staged/mart tables (stored as <table>.manifest.json)."""

    manifest_version: int = 1
    layer: str
    table: str
    built_at: datetime
    row_count: int
    inputs: list[InputRef]
    package_version: str
    notes: str | None = None


def derived_manifest_path(table_path: Path) -> Path:
    return table_path.with_suffix(".manifest.json")


def write_derived_manifest(manifest: DerivedManifest, table_path: Path) -> Path:
    path = derived_manifest_path(table_path)
    path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return path


def read_derived_manifest(table_path: Path) -> DerivedManifest:
    return DerivedManifest.model_validate_json(derived_manifest_path(table_path).read_text())
