"""Command-line interface: the `philly` entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from philly_assessments import catalog
from philly_assessments.ingest.snapshots import snapshot_carto_table
from philly_assessments.sources.carto import DEFAULT_PAGE_SIZE


def _cmd_snapshot(args: argparse.Namespace) -> int:
    result = snapshot_carto_table(
        args.table,
        dataset=args.dataset,
        data_dir=args.data_dir,
        page_size=args.page_size,
        limit=args.limit,
    )
    print(f"{result.manifest.row_count:,} rows -> {result.directory}")
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    refs = catalog.latest_snapshots(args.data_dir)
    if not refs:
        print("no snapshots found; run `philly snapshot` first")
        return 1
    header = f"{'view':<34} {'rows':>12}  {'fetched_at':<17} source"
    print(header)
    print("-" * len(header))
    for dataset in sorted(refs):
        ref = refs[dataset]
        rows = ref.manifest().row_count
        print(f"{ref.view_name:<34} {rows:>12,}  {ref.fetched_at:<17} {ref.source}")
    return 0


def _cmd_sql(args: argparse.Namespace) -> int:
    con = catalog.connect(args.data_dir)
    con.sql(args.query).show(max_rows=args.max_rows)
    return 0


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
    snapshot.set_defaults(func=_cmd_snapshot)

    catalog_cmd = subparsers.add_parser(
        "catalog", help="list the latest snapshot registered for each dataset"
    )
    catalog_cmd.add_argument("--data-dir", type=Path)
    catalog_cmd.set_defaults(func=_cmd_catalog)

    sql = subparsers.add_parser(
        "sql", help="run SQL against the latest raw snapshots (views named raw_<dataset>)"
    )
    sql.add_argument("query")
    sql.add_argument("--max-rows", type=int, default=40)
    sql.add_argument("--data-dir", type=Path)
    sql.set_defaults(func=_cmd_sql)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return args.func(args)
