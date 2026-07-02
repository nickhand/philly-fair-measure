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
    raw_refs = catalog.latest_snapshots(args.data_dir)
    derived_refs = catalog.list_derived(args.data_dir)
    if not raw_refs and not derived_refs:
        print("no snapshots found; run `philly snapshot` first")
        return 1
    header = f"{'view':<34} {'rows':>12}  {'as_of':<21} source"
    print(header)
    print("-" * len(header))
    for dataset in sorted(raw_refs):
        ref = raw_refs[dataset]
        rows = ref.manifest().row_count
        print(f"{ref.view_name:<34} {rows:>12,}  {ref.fetched_at:<21} {ref.source}")
    for ref in derived_refs:
        manifest = ref.manifest()
        built = manifest.built_at.strftime("%Y%m%dT%H%M%SZ")
        inputs = ", ".join(i.dataset for i in manifest.inputs)
        print(f"{ref.view_name:<34} {manifest.row_count:>12,}  {built:<21} {inputs}")
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    from philly_assessments.staging import build_all

    results = build_all(args.data_dir, only=args.tables)
    for result in results:
        print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_validate_sales(args: argparse.Namespace) -> int:
    from philly_assessments.validation import build_sale_validity

    result = build_sale_validity(args.data_dir)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_snapshot_all(args: argparse.Namespace) -> int:
    from philly_assessments import config

    failures = []
    for table, page_size in config.CORE_CARTO_TABLES.items():
        try:
            result = snapshot_carto_table(table, data_dir=args.data_dir, page_size=page_size)
            print(f"{result.manifest.row_count:,} rows -> {result.directory}")
        except Exception as exc:  # keep snapshotting the rest; report at the end
            logging.getLogger(__name__).exception("snapshot failed for %s", table)
            failures.append((table, exc))
    if failures:
        print(f"FAILED: {', '.join(table for table, _ in failures)}")
        return 1
    return 0


def _cmd_freshness(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from philly_assessments import config
    from philly_assessments.ingest.snapshots import FETCHED_AT_FORMAT

    latest = catalog.latest_snapshots(args.data_dir)
    now = datetime.now(UTC)
    stale = []
    for table in config.CORE_CARTO_TABLES:
        ref = latest.get(table)
        if ref is None:
            print(f"{table:<28} MISSING")
            stale.append(table)
            continue
        fetched = datetime.strptime(ref.fetched_at, FETCHED_AT_FORMAT).replace(tzinfo=UTC)
        age_days = (now - fetched).total_seconds() / 86_400
        status = "STALE" if age_days > args.max_age_days else "ok"
        print(f"{table:<28} {status:<8} {age_days:.1f}d old ({ref.fetched_at})")
        if status == "STALE":
            stale.append(table)
    return 1 if stale else 0


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

    stage = subparsers.add_parser(
        "stage", help="build staged tables from the latest raw snapshots"
    )
    stage.add_argument(
        "--tables", nargs="*", help="staged tables to build (default: all)", default=None
    )
    stage.add_argument("--data-dir", type=Path)
    stage.set_defaults(func=_cmd_stage)

    validate = subparsers.add_parser(
        "validate-sales", help="classify deed validity into marts/sale_validity.parquet"
    )
    validate.add_argument("--data-dir", type=Path)
    validate.set_defaults(func=_cmd_validate_sales)

    snapshot_all = subparsers.add_parser(
        "snapshot-all", help="snapshot every core table (the recurring snapshot job)"
    )
    snapshot_all.add_argument("--data-dir", type=Path)
    snapshot_all.set_defaults(func=_cmd_snapshot_all)

    freshness = subparsers.add_parser(
        "freshness",
        help="check snapshot ages; exit 1 if any core dataset is missing or stale",
    )
    freshness.add_argument("--max-age-days", type=float, default=8.0)
    freshness.add_argument("--data-dir", type=Path)
    freshness.set_defaults(func=_cmd_freshness)

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
