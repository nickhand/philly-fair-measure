"""Command-line interface: the `philly` entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from philly_assessments.ingest.snapshots import snapshot_carto_table
from philly_assessments.sources.carto import DEFAULT_PAGE_SIZE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="philly",
        description="Philadelphia property assessment data package",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="capture a raw snapshot of a source table")
    snapshot.add_argument("source", choices=("carto",), help="source API")
    snapshot.add_argument("table", help="table name, e.g. opa_properties_public")
    snapshot.add_argument(
        "--dataset", help="dataset name used in the storage path (defaults to the table name)"
    )
    snapshot.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    snapshot.add_argument("--limit", type=int, help="fetch at most this many rows (smoke tests)")
    snapshot.add_argument(
        "--data-dir", type=Path, help="data lake root (default ./data or $PHILLY_DATA_DIR)"
    )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.command == "snapshot":
        result = snapshot_carto_table(
            args.table,
            dataset=args.dataset,
            data_dir=args.data_dir,
            page_size=args.page_size,
            limit=args.limit,
        )
        print(f"{result.manifest.row_count:,} rows -> {result.directory}")
    return 0
