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


def _cmd_build_features(args: argparse.Namespace) -> int:
    from philly_assessments.features import build_sale_features

    result = build_sale_features(args.data_dir, min_sale_year=args.min_sale_year)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_train_baseline(args: argparse.Namespace) -> int:
    from philly_assessments.models import train_baseline

    result = train_baseline(args.data_dir, test_fraction=args.test_fraction)
    print(f"run {result.run_id} -> {result.run_dir}\n")
    columns = ("n", "rmse_log", "mape", "r2_log", "median_ratio", "cod", "prd", "prb")
    print(f"{'model':<16}" + "".join(f"{c:>13}" for c in columns))
    for model in ("lightgbm", "ridge", "opa_assessment"):
        row = result.overall[model]
        cells = []
        for column in columns:
            value = row.get(column)
            if value is None:
                cells.append(f"{'-':>13}")
            elif column == "n":
                cells.append(f"{value:>13,}")
            else:
                cells.append(f"{value:>13.4f}")
        print(f"{model:<16}" + "".join(cells))
    return 0


def _cmd_train_bayesian(args: argparse.Namespace) -> int:
    from philly_assessments.models.bayesian import train_bayesian

    result = train_bayesian(
        args.data_dir,
        test_fraction=args.test_fraction,
        draws=args.draws,
        tune=args.tune,
        chains=args.chains,
        cores=args.cores,
    )
    print(f"run {result.run_id} -> {result.run_dir}\n")
    row = result.overall
    for key in (
        "n",
        "rmse_log",
        "mape",
        "r2_log",
        "median_ratio",
        "cod",
        "prd",
        "prb",
        "coverage_90",
        "mean_pi_width_rel",
    ):
        value = row.get(key)
        print(f"{key:>20}: " + ("-" if value is None else f"{value:,.4f}"))
    return 0


def _cmd_build_market_areas(args: argparse.Namespace) -> int:
    from philly_assessments.features.market_areas import build_market_areas

    result = build_market_areas(args.data_dir, n_areas=args.n_areas, n_districts=args.n_districts)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_build_price_index(args: argparse.Namespace) -> int:
    from philly_assessments.features.price_index import build_price_index

    result = build_price_index(args.data_dir)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_screen_assessments(args: argparse.Namespace) -> int:
    from philly_assessments.validation.opa import build_assessment_screen

    result = build_assessment_screen(args.data_dir, chunk_size=args.chunk_size)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    for flag in sorted(result.flag_counts):
        print(f"  {flag:<26} {result.flag_counts[flag]:>9,}")
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

    build_features = subparsers.add_parser(
        "build-features", help="build marts/sale_features.parquet for arms-length sales"
    )
    build_features.add_argument("--min-sale-year", type=int, default=2016)
    build_features.add_argument("--data-dir", type=Path)
    build_features.set_defaults(func=_cmd_build_features)

    train = subparsers.add_parser(
        "train-baseline", help="train LightGBM + Ridge baselines and benchmark against OPA"
    )
    train.add_argument("--test-fraction", type=float, default=0.1)
    train.add_argument("--data-dir", type=Path)
    train.set_defaults(func=_cmd_train_baseline)

    bayes = subparsers.add_parser(
        "train-bayesian", help="train the hierarchical Bayesian model with predictive intervals"
    )
    bayes.add_argument("--test-fraction", type=float, default=0.1)
    bayes.add_argument("--draws", type=int, default=800)
    bayes.add_argument("--tune", type=int, default=800)
    bayes.add_argument("--chains", type=int, default=2)
    bayes.add_argument("--cores", type=int, default=1)
    bayes.add_argument("--data-dir", type=Path)
    bayes.set_defaults(func=_cmd_train_bayesian)

    market_areas = subparsers.add_parser(
        "build-market-areas", help="learn GMA-analog market areas from arms-length sales"
    )
    market_areas.add_argument("--n-areas", type=int, default=350)
    market_areas.add_argument("--n-districts", type=int, default=18)
    market_areas.add_argument("--data-dir", type=Path)
    market_areas.set_defaults(func=_cmd_build_market_areas)

    price_index = subparsers.add_parser(
        "build-price-index", help="build the district monthly price index"
    )
    price_index.add_argument("--data-dir", type=Path)
    price_index.set_defaults(func=_cmd_build_price_index)

    screen = subparsers.add_parser(
        "screen-assessments",
        help="score every residential property and flag OPA values outside the "
        "Bayesian predictive interval",
    )
    screen.add_argument("--chunk-size", type=int, default=50_000)
    screen.add_argument("--data-dir", type=Path)
    screen.set_defaults(func=_cmd_screen_assessments)

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
