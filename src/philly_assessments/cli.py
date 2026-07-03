"""Command-line interface: the `philly` entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from philly_assessments import catalog
from philly_assessments.ingest.snapshots import snapshot_carto_table
from philly_assessments.sources.carto import DEFAULT_PAGE_SIZE


def _cmd_snapshot(args: argparse.Namespace) -> int:
    if args.source == "arcgis":
        from philly_assessments.ingest.snapshots import snapshot_arcgis_layer
        from philly_assessments.sources.arcgis import SEPTA_ARCGIS_BASE

        base_url = SEPTA_ARCGIS_BASE if args.org == "septa" else None
        result = snapshot_arcgis_layer(
            args.table,
            dataset=args.dataset,
            data_dir=args.data_dir,
            limit=args.limit,
            base_url=base_url,
        )
    else:
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


def _cmd_build_condo_features(args: argparse.Namespace) -> int:
    from philly_assessments.features.condo_features import build_condo_features

    result = build_condo_features(args.data_dir)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_train_condo(args: argparse.Namespace) -> int:
    from philly_assessments.models.condo import train_condo

    result = train_condo(args.data_dir)
    print(f"run {result.run_id} -> {result.run_dir}\n")
    columns = ("n", "rmse_log", "mape", "r2_log", "median_ratio", "cod", "prd", "prb")
    print(f"{'model':<16}" + "".join(f"{c:>13}" for c in columns))
    for model, row in result.overall.items():
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
        nu_fixed=None if args.learn_nu else args.nu,
        spatial_basis=args.spatial_basis,
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


def _cmd_build_proximity(args: argparse.Namespace) -> int:
    from philly_assessments.features.proximity import build_proximity

    result = build_proximity(args.data_dir)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    return 0


def _cmd_screen_assessments(args: argparse.Namespace) -> int:
    from philly_assessments.validation.opa import build_assessment_screen

    result = build_assessment_screen(args.data_dir, chunk_size=args.chunk_size)
    print(f"{result.manifest.row_count:,} rows -> {result.path}")
    for flag in sorted(result.flag_counts):
        print(f"  {flag:<26} {result.flag_counts[flag]:>9,}")
    return 0


def _cmd_conformal_check(args: argparse.Namespace) -> int:
    import polars as pl

    from philly_assessments.models.conformal import conformal_check

    result = conformal_check(args.data_dir, alpha=args.alpha, k=args.k)
    print(f"conformal cross-check on {result.run_dir.name} (nominal {1 - args.alpha:.0%})\n")

    methods = ["conformal_global", "conformal_district", "conformal_knn", "bayesian"]
    labels = [m.removeprefix("conformal_") for m in methods]
    header = f"{'segment':<16}{'n':>9}" + "".join(f"{label:>16}" for label in labels)
    print(header)
    print("-" * len(header))
    segments = result.table.select("segment_type", "segment", "n").unique(
        maintain_order=True
    )
    for seg in segments.to_dicts():
        cells = []
        for method in methods:
            row = result.table.filter(
                (pl.col("method") == method)
                & (pl.col("segment_type") == seg["segment_type"])
                & (pl.col("segment") == seg["segment"])
            )
            if row.height:
                cells.append(
                    f"{row['coverage'][0]:>8.3f}/{row['median_width_log'][0]:<7.2f}"
                )
            else:
                cells.append(f"{'-':>16}")
        print(f"{seg['segment']:<16}{seg['n']:>9,}" + "".join(cells))

    spread = (
        result.district_coverage.group_by("method")
        .agg(
            pl.col("coverage").min().alias("min"),
            pl.col("coverage").max().alias("max"),
        )
        .sort("method")
    )
    print("\ncoverage across districts (min - max):")
    for row in spread.to_dicts():
        print(f"  {row['method']:<20} {row['min']:.3f} - {row['max']:.3f}")

    if result.flag_agreement is not None:
        print("\nscreen flag agreement (bayesian rows x conformal-knn columns):")
        pivot = result.flag_agreement.pivot(
            on="conformal_flag", index="bayesian_flag", values="len"
        ).fill_null(0)
        cols = [c for c in pivot.columns if c != "bayesian_flag"]
        print(f"  {'bayesian \\ conformal':<26}" + "".join(f"{c[:14]:>16}" for c in cols))
        for row in pivot.sort("bayesian_flag").to_dicts():
            print(
                f"  {row['bayesian_flag']:<26}"
                + "".join(f"{row[c]:>16,}" for c in cols)
            )
    return 0


def _cmd_acs_sensitivity(args: argparse.Namespace) -> int:
    import polars as pl

    from philly_assessments.diagnostics.acs_sensitivity import run_acs_sensitivity

    table = run_acs_sensitivity(args.data_dir)
    columns = ("n", "rmse_log", "r2_log", "median_ratio", "cod", "prd")
    for segment_type in table["segment_type"].unique(maintain_order=True).to_list():
        print(f"\n== {segment_type} ==")
        sub = table.filter(pl.col("segment_type") == segment_type)
        print(f"{'model':<16}{'segment':<14}" + "".join(f"{c:>13}" for c in columns))
        for row in sub.sort("segment", "model").to_dicts():
            cells = []
            for column in columns:
                value = row.get(column)
                if value is None:
                    cells.append(f"{'-':>13}")
                elif column == "n":
                    cells.append(f"{value:>13,}")
                else:
                    cells.append(f"{value:>13.4f}")
            print(f"{row['model']:<16}{row['segment']:<14}" + "".join(cells))
    return 0


def _cmd_ratio_study(args: argparse.Namespace) -> int:
    import polars as pl

    from philly_assessments.diagnostics.ratio_study import iaao_bridge, sale_chasing_check

    bridge = iaao_bridge(args.data_dir)
    columns = ("n", "n_trimmed", "median_ratio", "cod", "prd", "prb")
    print("IAAO convention bridge (identical out-of-time test sales)\n")
    print(f"{'estimator':<10}{'step':<18}{'segment':<10}" + "".join(f"{c:>13}" for c in columns))
    for row in bridge.to_dicts():
        cells = []
        for column in columns:
            value = row.get(column)
            if value is None:
                cells.append(f"{'-':>13}")
            elif column in ("n", "n_trimmed"):
                cells.append(f"{value:>13,}")
            else:
                cells.append(f"{value:>13.4f}")
        print(f"{row['estimator']:<10}{row['step']:<18}{row['segment']:<10}" + "".join(cells))

    chase = sale_chasing_check(args.data_dir)
    print("\nsale-chasing check: same roll vs sales the assessor could/couldn't see")
    print("(TASP ratios, 3xIQR-trimmed; drift removed by the index)\n")
    with pl.Config(tbl_cols=-1, tbl_width_chars=120):
        print(chase)
    return 0


def _cmd_aerial_pilot(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.aerial_change import pilot_summary, run_aerial_pilot

    table = run_aerial_pilot(
        args.data_dir,
        vintage_early=args.early,
        vintage_late=args.late,
        n_demolition=args.n_demolition,
        n_construction=args.n_construction,
        n_control=args.n_control,
    )
    summary = pilot_summary(table)
    print(f"\naerial change pilot: {args.early} vs {args.late} flights, "
          f"{table.height} parcels scored\n")
    header = (f"{'group':<18}{'metric':<12}{'n_event':>8}{'n_ctrl':>8}"
              f"{'AUC':>8}{'med_event':>11}{'med_ctrl':>10}")
    print(header)
    print("-" * len(header))
    for row in summary.to_dicts():
        print(
            f"{row['group']:<18}{row['metric'].removeprefix('score_'):<12}"
            f"{row['n_event']:>8,}{row['n_control']:>8,}"
            f"{row['auc_vs_control']:>8.3f}{row['median_event']:>11.3f}"
            f"{row['median_control']:>10.3f}"
        )
    print("\nexample tile pairs -> data/diagnostics/aerial_pilot_examples/")
    return 0


def _cmd_comps(args: argparse.Namespace) -> int:
    import polars as pl

    from philly_assessments.models.comps import find_comps, resolve_parcel

    candidates = resolve_parcel(args.query, args.data_dir)
    if not candidates:
        print(f"no property matches {args.query!r}")
        return 1
    if len(candidates) > 1:
        print("multiple matches; use a parcel id:")
        for c in candidates:
            print(f"  {c['parcel_id']}  {c['address']}")
        return 1
    parcel_id = candidates[0]["parcel_id"]
    result = find_comps(parcel_id, args.data_dir, k=args.k, window_years=args.window_years)

    t = result.target
    print(f"{t['address']}  (parcel {t['parcel_id']})")
    print(
        f"  {t.get('char_livable_area') or '?'} sqft {t.get('char_style')} "
        f"{t.get('char_era')}, interior condition {t.get('char_interior_condition')}"
    )
    print(f"  OPA market value: ${t.get('opa_market_value') or 0:,.0f}")
    from philly_assessments import config

    data_root = args.data_dir if args.data_dir is not None else config.data_dir()
    screen_path = data_root / "marts" / "assessment_screen.parquet"
    if screen_path.exists():
        row = (
            pl.scan_parquet(screen_path)
            .filter(pl.col("parcel_id") == parcel_id)
            .collect()
        )
        if row.height:
            r = row.to_dicts()[0]
            print(
                f"  model: ${r['model_median']:,.0f} "
                f"(90% PI ${r['model_pi_low_90']:,.0f} - ${r['model_pi_high_90']:,.0f}, "
                f"{r['interval_method']}) -> {r['assessment_flag']}"
            )

    print(f"\ntop {result.comps.height} comparable arms-length sales:")
    header = (
        f"  {'address':<26} {'sold':<11} {'price':>11} {'adj. today':>11} "
        f"{'sqft':>6} {'style':<9} {'dist':>6} {'sim':>5}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for c in result.comps.to_dicts():
        print(
            f"  {str(c['address'] or '?')[:26]:<26} "
            f"{c['sale_date']:%Y-%m-%d}  "
            f"${c['sale_price']:>10,.0f} ${c['price_adj_today']:>10,.0f} "
            f"{c['char_livable_area'] or 0:>6.0f} {str(c['char_style']):<9} "
            f"{c['distance_m'] or 0:>5.0f}m {c['similarity']:>5.2f}"
        )
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
    snapshot.add_argument("source", choices=("carto", "arcgis"), help="source API")
    snapshot.add_argument(
        "table", help="CARTO table (e.g. opa_properties_public) or ArcGIS service (PWD_PARCELS)"
    )
    snapshot.add_argument(
        "--dataset", help="dataset name used in the storage path (defaults to the table name)"
    )
    snapshot.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    snapshot.add_argument("--limit", type=int, help="fetch at most this many rows (smoke tests)")
    snapshot.add_argument(
        "--org",
        choices=("phl", "septa"),
        default="phl",
        help="ArcGIS org hosting the layer (SEPTA station layers live in SEPTA's org)",
    )
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

    condo_features = subparsers.add_parser(
        "build-condo-features", help="build marts/condo_sale_features.parquet"
    )
    condo_features.add_argument("--data-dir", type=Path)
    condo_features.set_defaults(func=_cmd_build_condo_features)

    train_condo_cmd = subparsers.add_parser(
        "train-condo", help="train the condominium model and benchmark against OPA"
    )
    train_condo_cmd.add_argument("--data-dir", type=Path)
    train_condo_cmd.set_defaults(func=_cmd_train_condo)

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
    bayes.add_argument("--nu", type=float, default=8.0, help="fixed Student-t dof")
    bayes.add_argument(
        "--learn-nu", action="store_true", help="learn nu (much slower sampling)"
    )
    bayes.add_argument(
        "--spatial-basis",
        action="store_true",
        help="add the RBF spatial basis (measured >15x slower sampling)",
    )
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

    proximity = subparsers.add_parser(
        "build-proximity",
        help="per-parcel SEPTA/park/road-class proximity features (quasi-static mart)",
    )
    proximity.add_argument("--data-dir", type=Path)
    proximity.set_defaults(func=_cmd_build_proximity)

    screen = subparsers.add_parser(
        "screen-assessments",
        help="score every residential property and flag OPA values outside the "
        "Bayesian predictive interval",
    )
    screen.add_argument("--chunk-size", type=int, default=50_000)
    screen.add_argument("--data-dir", type=Path)
    screen.set_defaults(func=_cmd_screen_assessments)

    conformal = subparsers.add_parser(
        "conformal-check",
        help="frequentist conformal intervals around LightGBM as an independent "
        "cross-check of the Bayesian screen",
    )
    conformal.add_argument("--alpha", type=float, default=0.10)
    conformal.add_argument("--k", type=int, default=500, help="calibration neighbors (knn method)")
    conformal.add_argument("--data-dir", type=Path)
    conformal.set_defaults(func=_cmd_conformal_check)

    acs = subparsers.add_parser(
        "acs-sensitivity",
        help="DIAGNOSTIC retrain measuring what the demographic-features ban "
        "costs in accuracy (never a production model)",
    )
    acs.add_argument("--data-dir", type=Path)
    acs.set_defaults(func=_cmd_acs_sensitivity)

    ratio_study = subparsers.add_parser(
        "ratio-study",
        help="IAAO convention bridge (our metrics vs OPA's reported ones) + "
        "sale-chasing checks",
    )
    ratio_study.add_argument("--data-dir", type=Path)
    ratio_study.set_defaults(func=_cmd_ratio_study)

    aerial = subparsers.add_parser(
        "aerial-pilot",
        help="aerial change-detection pilot: PASDA orthophoto change scores vs "
        "known demolitions/new construction (diagnostic)",
    )
    aerial.add_argument("--early", type=int, default=2020)
    aerial.add_argument("--late", type=int, default=2023)
    aerial.add_argument("--n-demolition", type=int, default=200)
    aerial.add_argument("--n-construction", type=int, default=200)
    aerial.add_argument("--n-control", type=int, default=300)
    aerial.add_argument("--data-dir", type=Path)
    aerial.set_defaults(func=_cmd_aerial_pilot)

    comps = subparsers.add_parser(
        "comps", help="comparable sales for a property (parcel id or address fragment)"
    )
    comps.add_argument("query")
    comps.add_argument("--k", type=int, default=10)
    comps.add_argument("--window-years", type=float, default=5.0)
    comps.add_argument("--data-dir", type=Path)
    comps.set_defaults(func=_cmd_comps)

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
