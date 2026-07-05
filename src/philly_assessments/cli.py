"""Command-line interface: the `philly` entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from philly_assessments import catalog
from philly_assessments.ingest.snapshots import snapshot_carto_table
from philly_assessments.sources.carto import DEFAULT_PAGE_SIZE
from philly_assessments.vocab import Market


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
    for dref in derived_refs:
        manifest = dref.manifest()
        built = manifest.built_at.strftime("%Y%m%dT%H%M%SZ")
        inputs = ", ".join(i.dataset for i in manifest.inputs)
        print(f"{dref.view_name:<34} {manifest.row_count:>12,}  {built:<21} {inputs}")
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

    result = train_baseline(args.data_dir, test_fraction=args.test_fraction, market=args.market)
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
        family=args.family,
        test_fraction=args.test_fraction,
        nu_fixed=None if args.learn_nu else args.nu,
        spatial_basis=args.spatial_basis,
        parcel_effect=args.parcel_effect,
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

    result = build_assessment_screen(
        args.data_dir, chunk_size=args.chunk_size, allow_stale=args.allow_stale
    )
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
    segments = result.table.select("segment_type", "segment", "n").unique(maintain_order=True)
    for seg in segments.to_dicts():
        cells = []
        for method in methods:
            row = result.table.filter(
                (pl.col("method") == method)
                & (pl.col("segment_type") == seg["segment_type"])
                & (pl.col("segment") == seg["segment"])
            )
            if row.height:
                cells.append(f"{row['coverage'][0]:>8.3f}/{row['median_width_log'][0]:<7.2f}")
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
    for stats in spread.to_dicts():
        print(f"  {stats['method']:<20} {stats['min']:.3f} - {stats['max']:.3f}")

    if result.flag_agreement is not None:
        print("\nscreen flag agreement (bayesian rows x conformal-knn columns):")
        pivot = result.flag_agreement.pivot(
            on="conformal_flag", index="bayesian_flag", values="len"
        ).fill_null(0)
        cols = [c for c in pivot.columns if c != "bayesian_flag"]
        print(f"  {'bayesian \\ conformal':<26}" + "".join(f"{c[:14]:>16}" for c in cols))
        for counts in pivot.sort("bayesian_flag").to_dicts():
            print(f"  {counts['bayesian_flag']:<26}" + "".join(f"{counts[c]:>16,}" for c in cols))
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


def _cmd_retail_market(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.retail_market import retail_vs_blend

    result = retail_vs_blend(args.data_dir)
    t = result.model_table
    print("blend vs retail (financed-only) model — median ratio / COD by segment\n")
    hdr = f"{'segment':<16}{'blend ratio':>13}{'blend COD':>11}"
    print(hdr + f"{'retail ratio':>14}{'retail COD':>12}")
    for seg in t["segment"].unique(maintain_order=True).to_list():
        b = t.filter((t["segment"] == seg) & (t["model"] == "blend")).to_dicts()[0]
        r = t.filter((t["segment"] == seg) & (t["model"] == "retail")).to_dicts()[0]
        print(
            f"{seg:<16}{b['median_ratio']:>13.3f}{b['cod']:>11.1f}"
            f"{r['median_ratio']:>14.3f}{r['cod']:>12.1f}"
        )
    print("\nOPA ratio under both value conventions (median OPA / value):\n")
    print(f"{'quintile':<10}{'% cash':>9}{'vs sale price':>15}{'vs retail value':>17}")
    for row in result.opa_convention_table.to_dicts():
        print(
            f"{row['quintile']:<10}{row['pct_cash']:>9.0%}"
            f"{row['opa_ratio_vs_sale_price']:>15.3f}{row['opa_ratio_vs_retail']:>17.3f}"
        )
    return 0


def _cmd_fairness_robustness(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.fairness_robustness import fairness_robustness

    r = fairness_robustness(args.data_dir)
    print("1. mechanism: coarse (OPA-style) vs rich model, median ratio by race\n")
    m = r.mechanism
    print(f"{'group':<28}{'OPA':>8}{'coarse':>9}{'rich':>8}")
    for g in m["group"].unique(maintain_order=True).to_list():
        vals = {row["model"]: row["median_ratio"] for row in m.filter(m["group"] == g).to_dicts()}
        print(
            f"{g:<28}{vals.get('opa', float('nan')):>8.3f}"
            f"{vals.get('coarse_model', float('nan')):>9.3f}"
            f"{vals.get('rich_model', float('nan')):>8.3f}"
        )

    print("\n2. Black-White median-ratio gap across temporal CV folds\n")
    print(f"{'fold':<6}{'test from':<12}{'OPA gap':>10}{'model gap':>11}")
    for row in r.cv.to_dicts():
        og = row["opa_black_white_gap"]
        mg = row["model_black_white_gap"]
        print(
            f"{row['fold']:<6}{row['test_from']:<12}"
            f"{(f'{og:+.3f}' if og is not None else '-'):>10}"
            f"{(f'{mg:+.3f}' if mg is not None else '-'):>11}"
        )

    print("\n3. full residential roll (sold + unsold): OPA vs model value by race\n")
    print(f"{'group':<28}{'n':>9}{'median OPA/model':>18}{'share OPA>110%':>16}")
    for row in r.full_roll.to_dicts():
        print(
            f"{row['group']:<28}{row['n_properties']:>9,}"
            f"{row['median_opa_over_model']:>18.3f}{row['share_opa_over_110pct']:>16.1%}"
        )
    return 0


def _cmd_regressivity_cv(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.fairness_robustness import vertical_regressivity_cv

    table, summary = vertical_regressivity_cv(args.data_dir)
    print("vertical regressivity (OPA q1/q5 ratio and PRD) across time periods\n")
    print(
        f"{'period from':<13}{'n':>8}{'q1/q5 sale':>12}{'q1/q5 retail':>14}"
        f"{'PRD sale':>10}{'PRD retail':>12}"
    )
    for r in table.to_dicts():
        print(
            f"{r['period_from']:<13}{r['n']:>8,}{r['q1q5_vs_sale']:>12.2f}"
            f"{r['q1q5_vs_retail']:>14.2f}{r['prd_vs_sale']:>10.3f}{r['prd_vs_retail']:>12.3f}"
        )
    print(
        f"\n  q1/q5 vs retail: mean {summary['q1q5_retail_mean']:.2f}, "
        f"min {summary['q1q5_retail_min']:.2f}  (>1 = regressive in every period)"
    )
    print(
        f"  PRD vs retail:   mean {summary['prd_retail_mean']:.3f}, "
        f"min {summary['prd_retail_min']:.3f}  (>1.03 = regressive)"
    )
    return 0


def _cmd_stability_audit(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.stability import (
        index_lookahead_bound,
        spatial_cv,
        temporal_cv,
    )

    temporal, t_sum = temporal_cv(args.data_dir)
    print("1. temporal rolling-origin CV (expanding window, out-of-time folds)\n")
    print(f"{'fold':<6}{'test from':<12}{'n_test':>8}{'COD':>8}{'ratio':>8}")
    for r in temporal.to_dicts():
        print(
            f"{r['fold']:<6}{r['test_from']:<12}{r['n_test']:>8,}{r['cod']:>8.1f}"
            f"{r['median_ratio']:>8.3f}"
        )
    print(
        f"  -> COD {t_sum['cod_mean']:.1f} ± {t_sum['cod_sd']:.1f} "
        f"(range {t_sum['cod_min']:.1f}-{t_sum['cod_max']:.1f})"
    )

    spatial, s_sum = spatial_cv(args.data_dir)
    print("\n2. spatial leave-one-district-out CV (adversarial — unseen geography)\n")
    print(
        f"  COD {s_sum['cod_mean']:.1f} ± {s_sum['cod_sd']:.1f} across "
        f"{s_sum['folds']} districts (range {s_sum['cod_min']:.1f}-{s_sum['cod_max']:.1f})"
    )
    worst = spatial.head(3).to_dicts()
    print(
        "  worst held-out districts: "
        + ", ".join(f"{r['held_out_district']} {r['cod']:.0f}" for r in worst)
    )

    la = index_lookahead_bound(args.data_dir)
    print("\n3. price-index look-ahead bound (magnitude of test-set time adjustment)\n")
    print(
        f"  mean |time adjustment| on test sales = {la['mean_abs_timeadj_pct']:.2%} "
        f"(p95 {la['p95_abs_timeadj_pct']:.2%}); the leaky component is a fraction of this."
    )
    print(f"  max index drift across the test window = {la['max_index_drift_over_window_pct']:.2%}")
    return 0


def _cmd_robustness_audit(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.robustness import robustness_audit

    result = robustness_audit(args.data_dir)
    print("1. char-leakage bound — model vs OPA by post-sale-permit status\n")
    cl = result.char_leakage
    print(f"{'subset':<38}{'n':>7}{'model COD':>11}{'OPA COD':>9}{'edge':>7}{'model ratio':>13}")
    for r in cl.to_dicts():
        print(
            f"{r['subset']:<38}{r['n']:>7,}{r['model_cod']:>11.1f}{r['opa_cod']:>9.1f}"
            f"{r['model_cod_edge']:>7.1f}{r['model_ratio']:>13.3f}"
        )
    print("\n2. racial gap under both value conventions (median OPA / value)\n")
    print(f"{'group':<28}{'n':>8}{'% cash':>8}{'vs sale price':>15}{'vs retail':>11}")
    for r in result.racial_conventions.to_dicts():
        print(
            f"{r['group']:<28}{r['n']:>8,}{r['pct_cash']:>8.0%}"
            f"{r['opa_ratio_vs_sale_price']:>15.3f}{r['opa_ratio_vs_retail']:>11.3f}"
        )
    return 0


def _cmd_channel_decomp(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.channel import channel_decomposition

    result = channel_decomposition(args.data_dir)
    t = result.table
    print("cash discount by control stage (negative = cash sells below financed)\n")
    print(f"{'segment':<10}{'raw':>10}{'+hedonic':>12}{'+distress':>12}{'  95% CI (pure)':>22}")
    for seg in t["segment"].unique(maintain_order=True).to_list():
        s = {r["stage"]: r for r in t.filter(t["segment"] == seg).to_dicts()}
        ci = s["distress"]
        ci_str = f"[{ci['ci_low']:+.1%}, {ci['ci_high']:+.1%}]" if ci["ci_low"] is not None else ""
        print(
            f"{seg:<10}{s['raw']['cash_discount_pct']:>+10.1%}"
            f"{s['hedonic']['cash_discount_pct']:>+12.1%}"
            f"{s['distress']['cash_discount_pct']:>+12.1%}{ci_str:>22}"
        )
    i = result.interaction
    print(
        f"\npure channel discount, clean house:      {i['cash_discount_clean_pct']:+.1%}"
        f"\npure channel discount, distressed house: {i['cash_discount_distressed_pct']:+.1%}"
        f"  (distress attenuates by {i['cash_x_distress_pct_points']:+.1%} pts)"
    )
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
    print(
        f"\naerial change pilot: {args.early} vs {args.late} flights, "
        f"{table.height} parcels scored\n"
    )
    header = (
        f"{'group':<18}{'metric':<12}{'n_event':>8}{'n_ctrl':>8}"
        f"{'AUC':>8}{'med_event':>11}{'med_ctrl':>10}"
    )
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


def _cmd_aerial_score(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.aerial_change import run_aerial_score

    scores = run_aerial_score(
        args.data_dir,
        vintage_early=args.early,
        vintage_late=args.late,
        n_control=args.n_control,
        limit=args.limit,
    )
    flagged = scores.filter(scores["aerial_change_flag"])
    print(
        f"\n{scores.height:,} flagged screen parcels scored ({args.early} vs {args.late}); "
        f"{flagged.height:,} show aerial change above the control-calibrated threshold"
    )
    print("rerun `philly screen-assessments` to embed the evidence columns")
    return 0


def _cmd_facade_coverage(args: argparse.Namespace) -> int:
    from philly_assessments.diagnostics.facade import coverage_summary, facade_coverage

    table = facade_coverage(args.data_dir, n_sample=args.n_sample)
    overall, by_district = coverage_summary(table)
    print(f"\nmapillary facade coverage ({table.height:,} sampled parcels)\n")
    for row in overall.to_dicts():
        print(f"  {row['cut']:<28} {row['coverage']:.1%}")
    print(f"\n{'district':<12}{'any usable':>12}{'2020+':>10}{'n':>7}")
    for row in by_district.to_dicts():
        print(
            f"{row['loc_district']:<12}{row['any_usable']:>12.1%}"
            f"{row['usable_2020plus']:>10.1%}{row['n']:>7,}"
        )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from philly_assessments.report import build_property_report

    try:
        path = build_property_report(args.query, args.data_dir, args.out)
    except KeyError as exc:
        print(exc.args[0])
        return 1
    print(f"report -> {path}")
    return 0


def _cmd_export_web_stats(args: argparse.Namespace) -> int:
    from philly_assessments.web_stats import export_web_stats

    stats = export_web_stats(args.data_dir, args.out)
    meta = stats["meta"]
    print(f"web stats -> {args.out} (run {meta['model_run_id']}, n_test {meta['n_test']:,})")
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    from philly_assessments.api import create_app

    uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
    return 0


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    from philly_assessments.report import build_property_report, leaderboards

    boards = leaderboards(args.data_dir, n=args.n, plausible=not args.extremes)
    mode = "raw extremes (incl. model blind spots)" if args.extremes else "plausible appeal band"
    print(f"assessment leaderboard — over/under lists: {mode}")
    titles = {
        "over_assessed": "MOST OVER-ASSESSED  (OPA above the model)",
        "under_assessed": "MOST UNDER-ASSESSED  (OPA below the model)",
        "non_uniform_block": "LEAST UNIFORM BLOCKS  (a home vs its identical twins)",
    }
    which = {
        "all": list(boards),
        "over": ["over_assessed"],
        "under": ["under_assessed"],
        "nonuniform": ["non_uniform_block"],
    }[args.kind]

    parcels: list[str] = []
    for key in which:
        print(f"\n{titles[key]}")
        for r in boards[key].iter_rows(named=True):
            parcels.append(str(r["parcel_id"]))
            addr = str(r["address"] or "")[:34]
            if key == "non_uniform_block":
                gap = (r["opa_vs_twin_median"] - 1) * 100
                print(
                    f"  {r['parcel_id']}  {addr:<34} ${r['opa_market_value']:>10,.0f}  "
                    f"{gap:+.0f}% vs {int(r['twin_n'])} identical twins"
                )
            else:
                print(
                    f"  {r['parcel_id']}  {addr:<34} OPA ${r['opa_market_value']:>10,.0f}  "
                    f"model ${r['model_median']:>10,.0f}  {r['opa_vs_model_ratio']:.1f}x  "
                    f"z {r['screen_z']:+.1f}"
                )

    if args.reports:
        made = 0
        for pid in dict.fromkeys(parcels):  # dedup, preserve order
            try:
                build_property_report(pid, args.data_dir)
                made += 1
            except Exception as exc:  # noqa: BLE001 — skip a bad parcel, keep the rest
                print(f"  (report failed for {pid}: {exc})")
        print(f"\n{made} reports written under data/reports/")
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
        row = pl.scan_parquet(screen_path).filter(pl.col("parcel_id") == parcel_id).collect()
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

    stage = subparsers.add_parser("stage", help="build staged tables from the latest raw snapshots")
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
    train.add_argument(
        "--market",
        choices=tuple(Market),
        default=Market.BLEND,
        help="retail = train on mortgage-financed sales only (predicts retail value)",
    )
    train.add_argument("--data-dir", type=Path)
    train.set_defaults(func=_cmd_train_baseline)

    bayes = subparsers.add_parser(
        "train-bayesian", help="train the hierarchical Bayesian model with predictive intervals"
    )
    bayes.add_argument(
        "--family",
        choices=("residential", "condo"),
        default="residential",
        help="property family: rowhome mart (default) or the condo-unit mart",
    )
    bayes.add_argument("--test-fraction", type=float, default=0.1)
    bayes.add_argument("--draws", type=int, default=800)
    bayes.add_argument("--tune", type=int, default=800)
    bayes.add_argument("--chains", type=int, default=2)
    bayes.add_argument("--cores", type=int, default=1)
    bayes.add_argument("--nu", type=float, default=8.0, help="fixed Student-t dof")
    bayes.add_argument("--learn-nu", action="store_true", help="learn nu (much slower sampling)")
    bayes.add_argument(
        "--spatial-basis",
        action="store_true",
        help="add the RBF spatial basis (measured >15x slower sampling)",
    )
    bayes.add_argument(
        "--parcel-effect",
        action="store_true",
        help="add per-parcel latent quality (measured ~no gain over the "
        "prev-price covariate; ~29k params)",
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
    screen.add_argument(
        "--allow-stale",
        action="store_true",
        help="build even if a model run predates the feature mart (downgrades "
        "the coherence refusal to a warning; the flags may be garbage)",
    )
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

    regressivity = subparsers.add_parser(
        "regressivity-cv",
        help="vertical regressivity (q1/q5 ratio, PRD) across time periods and "
        "both value conventions — the claim that survives everything",
    )
    regressivity.add_argument("--data-dir", type=Path)
    regressivity.set_defaults(func=_cmd_regressivity_cv)

    fairness = subparsers.add_parser(
        "fairness-robustness",
        help="is the race-gap elimination real? coarse-vs-rich mechanism, "
        "gap across CV folds, and full-roll (sold+unsold) check",
    )
    fairness.add_argument("--data-dir", type=Path)
    fairness.set_defaults(func=_cmd_fairness_robustness)

    stability = subparsers.add_parser(
        "stability-audit",
        help="temporal + spatial cross-validation and the price-index "
        "look-ahead bound (accuracy is a distribution, not one split)",
    )
    stability.add_argument("--data-dir", type=Path)
    stability.set_defaults(func=_cmd_stability_audit)

    robustness = subparsers.add_parser(
        "robustness-audit",
        help="char-leakage bound + racial gap under both value conventions "
        "(the two measurements a hostile reviewer would demand)",
    )
    robustness.add_argument("--data-dir", type=Path)
    robustness.set_defaults(func=_cmd_robustness_audit)

    channel = subparsers.add_parser(
        "channel-decomp",
        help="decompose the cash-vs-financed sale gap into pure channel "
        "discount vs distress-driven value (retail-value diagnostic)",
    )
    channel.add_argument("--data-dir", type=Path)
    channel.set_defaults(func=_cmd_channel_decomp)

    retail = subparsers.add_parser(
        "retail-market",
        help="blend vs financed-only retail model + OPA ratio under both "
        "cash and retail value conventions",
    )
    retail.add_argument("--data-dir", type=Path)
    retail.set_defaults(func=_cmd_retail_market)

    ratio_study = subparsers.add_parser(
        "ratio-study",
        help="IAAO convention bridge (our metrics vs OPA's reported ones) + sale-chasing checks",
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

    aerial_score = subparsers.add_parser(
        "aerial-score",
        help="score the screen's flagged parcels for aerial change "
        "(control-calibrated; rerun screen-assessments to embed)",
    )
    aerial_score.add_argument("--early", type=int, default=2023)
    aerial_score.add_argument("--late", type=int, default=2025)
    aerial_score.add_argument("--n-control", type=int, default=300)
    aerial_score.add_argument("--limit", type=int)
    aerial_score.add_argument("--data-dir", type=Path)
    aerial_score.set_defaults(func=_cmd_aerial_score)

    facade = subparsers.add_parser(
        "facade-coverage",
        help="Mapillary usable-facade coverage check (stage-1 gate for the "
        "facade-condition layer; needs MAPILLARY_TOKEN)",
    )
    facade.add_argument("--n-sample", type=int, default=2000)
    facade.add_argument("--data-dir", type=Path)
    facade.set_defaults(func=_cmd_facade_coverage)

    report = subparsers.add_parser(
        "report",
        help="static HTML property report / appeal packet (parcel id or address)",
    )
    report.add_argument("query")
    report.add_argument("--out", type=Path, help="output directory (default data/reports/)")
    report.add_argument("--data-dir", type=Path)
    report.set_defaults(func=_cmd_report)

    leaderboard = subparsers.add_parser(
        "leaderboard",
        help="rank the most over-/under-assessed properties and least-uniform blocks",
    )
    leaderboard.add_argument(
        "--kind", choices=("all", "over", "under", "nonuniform"), default="all"
    )
    leaderboard.add_argument("--n", type=int, default=20, help="rows per list (default 20)")
    leaderboard.add_argument(
        "--extremes",
        action="store_true",
        help="show raw biggest-disagreement outliers (incl. model blind spots) "
        "instead of the plausible appeal band",
    )
    leaderboard.add_argument(
        "--reports", action="store_true", help="also render the HTML report for each listed parcel"
    )
    leaderboard.add_argument("--data-dir", type=Path)
    leaderboard.set_defaults(func=_cmd_leaderboard)

    api = subparsers.add_parser(
        "api", help="serve the public-dashboard JSON API (backs the web/ front door)"
    )
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--data-dir", type=Path)
    api.set_defaults(func=_cmd_api)

    web_stats = subparsers.add_parser(
        "export-web-stats",
        help="recompute the dashboard's headline stats into web/src/data/siteStats.json",
    )
    web_stats.add_argument("--out", type=Path, default=Path("web/src/data/siteStats.json"))
    web_stats.add_argument("--data-dir", type=Path)
    web_stats.set_defaults(func=_cmd_export_web_stats)

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
    exit_code: int = args.func(args)
    return exit_code
