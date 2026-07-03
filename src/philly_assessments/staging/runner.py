"""Build staged tables from the latest raw snapshots and write them with manifests."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from philly_assessments import __version__, catalog, config
from philly_assessments.ingest.manifests import (
    DerivedManifest,
    InputRef,
    write_derived_manifest,
)
from philly_assessments.staging import tables
from philly_assessments.staging.parcels import stg_parcels

logger = logging.getLogger(__name__)

# staged table name -> (builder, raw datasets it consumes, in argument order)
BUILDERS: dict[str, tuple[Callable[..., pl.LazyFrame], tuple[str, ...]]] = {
    "assessments": (tables.stg_assessments, ("assessments",)),
    "opa_properties": (tables.stg_opa_properties, ("opa_properties_public",)),
    "deeds": (tables.stg_deeds, ("rtt_summary", "opa_properties_public")),
    "permits": (tables.stg_permits, ("permits",)),
    "violations": (tables.stg_violations, ("violations",)),
    "parcels": (stg_parcels, ("pwd_parcels", "opa_properties_public")),
    "delinquencies": (tables.stg_delinquencies, ("real_estate_tax_delinquencies",)),
    "demolitions": (tables.stg_demolitions, ("demolitions",)),
}


@dataclass(frozen=True)
class BuildResult:
    table: str
    path: Path
    manifest: DerivedManifest


def build_all(
    data_dir: Path | None = None, only: Sequence[str] | None = None
) -> list[BuildResult]:
    root = data_dir if data_dir is not None else config.data_dir()
    latest = catalog.latest_snapshots(data_dir)
    staged_dir = root / "staged"
    staged_dir.mkdir(parents=True, exist_ok=True)

    selected = dict(BUILDERS) if only is None else {name: BUILDERS[name] for name in only}
    results = []
    for table_name, (builder, input_datasets) in selected.items():
        missing = [d for d in input_datasets if d not in latest]
        if missing:
            raise FileNotFoundError(
                f"staged table {table_name!r} needs raw snapshots {missing}; "
                "run `philly snapshot` first"
            )
        refs = [latest[d] for d in input_datasets]
        frame = builder(*(pl.scan_parquet(ref.data_path) for ref in refs)).collect()

        path = staged_dir / f"{table_name}.parquet"
        tmp = path.with_suffix(".parquet.tmp")
        frame.write_parquet(tmp, compression="zstd")
        tmp.rename(path)

        manifest = DerivedManifest(
            layer="staged",
            table=table_name,
            built_at=datetime.now(UTC),
            row_count=frame.height,
            inputs=[InputRef(dataset=r.dataset, fetched_at=r.fetched_at) for r in refs],
            package_version=__version__,
        )
        write_derived_manifest(manifest, path)
        logger.info("staged %s: %s rows -> %s", table_name, f"{frame.height:,}", path)
        results.append(BuildResult(table=table_name, path=path, manifest=manifest))
    return results
