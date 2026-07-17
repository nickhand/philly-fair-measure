"""Export the dashboard's headline statistics to a JSON file.

The web app's Findings / Trust / Methodology pages carry measured results
(ratio-study cards, financed tier ratios, the cash/financed split, the
historical redistribution series). Those numbers must never be hand-edited:
`fair-measure export-web-stats` recomputes every one from the latest baseline run's
artifacts and the marts, and writes `web/src/data/siteStats.json`, which the
frontend imports at build time. Regenerate after every retrain/screen rebuild.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.metrics import evaluate_estimates
from philly_fair_measure.models.scoring import latest_run_dir

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("web/src/data/siteStats.json")
DEFAULT_ANNUAL_REPORT_CONFIG = Path("annual_report.json")
PHILADELPHIA_TZ = ZoneInfo("America/New_York")


def load_annual_report_settings(path: Path = DEFAULT_ANNUAL_REPORT_CONFIG) -> dict[str, Any]:
    """Load and validate the externally sourced settings for one assessment cycle."""

    settings = json.loads(path.read_text())
    required = {
        "schema_version",
        "tax_year",
        "comparison_year",
        "effective_date",
        "sales_cutoff",
        "status",
        "opa_study_verdict",
        "appeal_deadlines",
        "sources",
    }
    missing = required - set(settings)
    if missing:
        raise ValueError(f"annual report config is missing: {sorted(missing)}")
    if settings["schema_version"] != 1:
        raise ValueError("annual report config schema_version must be 1")
    if settings["status"] not in {"provisional", "final"}:
        raise ValueError("annual report status must be provisional or final")
    if settings["opa_study_verdict"] not in {
        "within_recommended_ranges",
        "outside_recommended_ranges",
        "mixed",
    }:
        raise ValueError("annual report opa_study_verdict is invalid")

    tax_year = int(settings["tax_year"])
    comparison_year = int(settings["comparison_year"])
    if comparison_year >= tax_year:
        raise ValueError("annual report comparison_year must precede tax_year")
    effective_date = date.fromisoformat(str(settings["effective_date"]))
    date.fromisoformat(str(settings["sales_cutoff"]))
    if effective_date.year != tax_year:
        raise ValueError("annual report effective_date must fall in tax_year")

    deadline_keys = {"first_level_review", "formal_appeal"}
    deadlines = settings["appeal_deadlines"]
    if not isinstance(deadlines, dict) or deadline_keys - set(deadlines):
        raise ValueError(f"annual report appeal_deadlines must include: {sorted(deadline_keys)}")
    for key in deadline_keys:
        date.fromisoformat(str(deadlines[key]))

    source_keys = {
        "opa_methodology_url",
        "opa_ratio_studies_url",
        "iaao_ratio_study_url",
        "notebook_url",
    }
    sources = settings["sources"]
    if not isinstance(sources, dict) or source_keys - set(sources):
        raise ValueError(f"annual report sources must include: {sorted(source_keys)}")
    if any(not str(sources[key]).startswith("https://") for key in source_keys):
        raise ValueError("annual report source URLs must use https")
    return settings


def _req(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"metric {name} is unexpectedly None — sample too small?")
    return value


def _card(estimate: np.ndarray, price: np.ndarray) -> dict[str, float | str]:
    from philly_fair_measure.models.metrics import vertical_equity_indicator

    m = evaluate_estimates(estimate, price)
    vei = vertical_equity_indicator(estimate, price)
    return {
        "median_ratio": round(_req(m.median_ratio, "median_ratio"), 3),
        "cod": round(_req(m.cod, "cod"), 1),
        "prd": round(_req(m.prd, "prd"), 3),
        "prb": round(_req(m.prb, "prb"), 3),
        "mape_pct": round(_req(m.mape, "mape") * 100, 1),
        # IAAO 2025 exposure-draft primary vertical-equity test (§8.2.1)
        "vei": round(_req(vei.vei, "vei"), 1),
        "vei_verdict": vei.verdict,
    }


def _benchmark_validation(card: dict[str, dict[str, float | str]]) -> dict[str, Any]:
    """Compare model and OPA regressivity by distance from each metric's ideal."""

    ideals = {"prd": 1.0, "prb": 0.0, "vei": 0.0}
    directions: dict[str, str] = {}
    for metric, ideal in ideals.items():
        model_distance = abs(float(card["model"][metric]) - ideal)
        opa_distance = abs(float(card["opa"][metric]) - ideal)
        directions[metric] = (
            "tie"
            if np.isclose(model_distance, opa_distance)
            else "model_fairer"
            if model_distance < opa_distance
            else "opa_fairer"
        )
    values = set(directions.values())
    verdict = (
        "model_less_regressive"
        if values == {"model_fairer"}
        else "opa_less_regressive"
        if values == {"opa_fairer"}
        else "tie"
        if values == {"tie"}
        else "mixed"
    )
    return {
        "basis": "Out-of-time financed sales with IAAO 3×IQR trimming",
        "metric_directions": directions,
        "verdict": verdict,
    }


def _iqr_trim_mask(ratio: np.ndarray) -> np.ndarray:
    """IAAO 3×IQR ratio trim — the same assesspy implementation the ratio-study
    bridge and the report card use, so the exported numbers match the docs."""
    from philly_fair_measure.diagnostics.ratio_study import _iaao_outlier_mask

    return np.asarray(~_iaao_outlier_mask(ratio))


# Philadelphia FY2025 property-tax rate: 0.6317% city + 0.7681% school.
MILLAGE = 0.013998


def _tax_shift(screen: pl.DataFrame) -> dict[str, Any]:
    """What adopting our assessments would do at today's tax rate.

    Philadelphia under-assesses its most expensive homes, so correcting the roll
    is found revenue, not just a reshuffle: at the current rate the city collects
    more, and the increase falls on the top, while the over-assessed cheapest
    homes get relief. No rate change and no new tax law. Because the increase at
    the top outweighs the relief at the bottom, the net is positive. Uses the
    displayed model estimate (`display_median`) against OPA's market value over
    every scored residential + condo property.
    """
    opa = screen["opa_market_value"].to_numpy().astype(np.float64)
    model = screen["display_median"].to_numpy().astype(np.float64)
    ok = np.isfinite(opa) & (opa > 0) & np.isfinite(model) & (model > 0)
    opa, model = opa[ok], model[ok]

    home_shift = MILLAGE * (model - opa)  # per-home change in yearly tax at today's rate
    edges = np.quantile(opa, [0.2, 0.4, 0.6, 0.8])
    bucket = np.digitize(opa, edges)  # 0..4, cheapest to priciest by OPA value
    names = ["cheapest fifth", "second fifth", "middle fifth", "fourth fifth", "priciest fifth"]
    tiers: list[dict[str, Any]] = [
        {
            "name": name,
            "home_usd": round(float(home_shift[bucket == i].mean())),
            "total_musd": round(float(home_shift[bucket == i].sum()) / 1e6, 1),
        }
        for i, name in enumerate(names)
    ]
    return {
        "millage_pct": round(MILLAGE * 100, 2),
        "base_change_pct": round((model.sum() / opa.sum() - 1) * 100, 1),
        # Net new revenue at the current rate — the city collects more because the
        # under-assessed top pays more than the over-assessed bottom is relieved.
        "new_revenue_musd": round(float(home_shift.sum()) / 1e6),
        "cheapest_home_usd": tiers[0]["home_usd"],
        "priciest_home_usd": tiers[-1]["home_usd"],
        "tiers": tiers,
    }


def export_web_stats(
    data_dir: Path | None = None,
    out_path: Path = DEFAULT_OUT,
    annual_report_config: Path = DEFAULT_ANNUAL_REPORT_CONFIG,
) -> dict[str, Any]:
    root = data_dir if data_dir is not None else config.data_dir()
    run_dir = latest_run_dir("baseline", root)
    run_id = run_dir.name.removeprefix("run_id=")

    preds = pl.read_parquet(run_dir / "predictions.parquet")
    if "pred_point" not in preds.columns:  # pre-stack runs name the point pred_lightgbm
        preds = preds.rename({"pred_lightgbm": "pred_point"})
    sf = pl.read_parquet(root / "marts" / "sale_features.parquet")
    joined = preds.join(
        sf.select("sale_id", "time_adj_log", "fin_cash_sale"), on="sale_id", how="left"
    ).drop_nulls(["sale_price", "pred_point", "opa_assessment"])

    price = joined["sale_price"].to_numpy().astype(np.float64)
    model = joined["pred_point"].to_numpy().astype(np.float64)
    opa = joined["opa_assessment"].to_numpy().astype(np.float64)
    adj = np.exp(joined["time_adj_log"].fill_null(0.0).to_numpy().astype(np.float64))
    financed = (joined["fin_cash_sale"].fill_null(1.0) == 0.0).to_numpy()

    # drop_nulls does NOT drop float NaN (polars NaN != null — the recurring
    # gotcha): a few dozen OPA values are NaN and would poison the percentile
    # trim below. Keep only rows finite in every array.
    ok = np.isfinite(price) & (price > 0) & np.isfinite(model) & np.isfinite(opa)
    price, model, opa, adj, financed = (price[ok], model[ok], opa[ok], adj[ok], financed[ok])

    # Full sample, out-of-time — what a homeowner actually experiences.
    full_card = {"opa": _card(opa, price), "model": _card(model, price)}

    # IAAO-standard basis: FINANCED sales (the standard's "typical financing"
    # market-value definition — see docs/report-assessment-equity.md), with
    # time-adjusted sale prices (the model's estimate moves with the index, so
    # its TASP ratio equals its raw ratio; OPA's does not) and the assesspy
    # 3×IQR ratio trim on each arm.
    tasp = price * adj
    f = financed
    opa_mask = _iqr_trim_mask(opa[f] / tasp[f])
    model_mask = _iqr_trim_mask(model[f] / price[f])
    iaao_card = {
        "opa": _card(opa[f][opa_mask], tasp[f][opa_mask]),
        "model": _card(model[f][model_mask], price[f][model_mask]),
    }

    # Financed-only tier ratios (the "regressivity in one picture" numbers).
    fp, fm, fo = price[financed], model[financed], opa[financed]
    edges = np.quantile(fp, [0.2, 0.8])
    q1, q5 = fp <= edges[0], fp >= edges[1]
    tiers = {
        "q1": {
            "opa_pct": round(float(np.median(fo[q1] / fp[q1])) * 100),
            "model_pct": round(float(np.median(fm[q1] / fp[q1])) * 100),
        },
        "q5": {
            "opa_pct": round(float(np.median(fo[q5] / fp[q5])) * 100),
            "model_pct": round(float(np.median(fm[q5] / fp[q5])) * 100),
        },
    }

    # Cash/financed structure: overall share on the whole sale base; the
    # cheapest-fifth share on the RECENT market (the out-of-time test slice),
    # which is what the Findings sentence describes.
    cash_flag = sf["fin_cash_sale"].fill_null(1.0).to_numpy() == 1.0
    share_all = float(cash_flag.mean())
    test_q1 = price <= float(np.quantile(price, 0.2))
    share_q1 = float((~financed[test_q1]).mean())
    # Median within-district price gap, cash vs financed (needs both sides).
    gaps: list[float] = []
    for _, d in sf.select("loc_district", "sale_price", "fin_cash_sale").group_by("loc_district"):
        c = d.filter(pl.col("fin_cash_sale") == 1.0)["sale_price"]
        f = d.filter(pl.col("fin_cash_sale") == 0.0)["sale_price"]
        if c.len() >= 50 and f.len() >= 50:
            gaps.append(float(c.median()) / float(f.median()) - 1.0)  # type: ignore[arg-type]
    discount_pct = round(float(np.median(gaps)) * 100) if gaps else None

    # Historical redistribution (the Findings bar chart) — financed benchmark.
    from philly_fair_measure.diagnostics.historical_redistribution import (
        historical_redistribution,
    )

    redis = historical_redistribution(root)
    fin_rows = redis.filter(pl.col("benchmark") == "financed")
    raw_rows = redis.filter(pl.col("benchmark") == "raw_sale")
    years = [
        {
            "year": int(r["year"]),
            "millions": round(r["citywide_tax_shifted_usd"] / 1e6),
            "partial": bool(r["partial_year"]),
        }
        for r in fin_rows.to_dicts()
    ]
    full = fin_rows.filter(~pl.col("partial_year"))
    raw_full = raw_rows.filter(~pl.col("partial_year"))
    redistribution = {
        "years": years,
        "total_financed_musd": round(float(full["citywide_tax_shifted_usd"].sum()) / 1e6),
        "total_raw_musd": round(float(raw_full["citywide_tax_shifted_usd"].sum()) / 1e6),
        "per_resident_usd": round(float(full["per_resident_usd"].sum())),
        "year_span": (
            f"{full['year'].to_list()[0] if full.height else 0}"
            f"–{full['year'].to_list()[-1] if full.height else 0}"
        ),
    }

    # measured interval coverage from the latest bayesian run — the "sales
    # landing inside our stated range" row on the methods page must be a
    # measurement, not a promise
    bayes_dir = latest_run_dir("bayesian", root)
    bayes_overall = (
        pl.read_parquet(bayes_dir / "evaluation.parquet")
        .filter(pl.col("segment_type") == "overall")
        .to_dicts()[0]
    )
    coverage_pct = round(float(bayes_overall["coverage_90"]) * 100)

    # screen counts + the full 3-model results rows: the single committed
    # source `fair-measure sync-docs` renders README/model.md numbers from,
    # so the docs can be CI-checked against this file without the data lake
    from philly_fair_measure.validation.screen_audit import audit_screen
    from philly_fair_measure.vocab import AssessmentFlag

    screen_df = pl.read_parquet(root / "marts" / "assessment_screen.parquet")
    audit = audit_screen(screen_df)
    flags = audit["flags"]

    def _flag_total(flag: str) -> int:
        return sum(count for key, count in flags.items() if key.endswith(f"/{flag}"))

    screen = {
        "properties": audit["rows"],
        "over": _flag_total(str(AssessmentFlag.OVER)),
        "under": _flag_total(str(AssessmentFlag.UNDER)),
        "watch": audit["watch"],
        "insufficient": _flag_total(str(AssessmentFlag.INSUFFICIENT)),
        "by_family_flag": flags,
    }

    tax_shift = _tax_shift(screen_df)

    # Doucet robustness: the regressivity tiers re-binned by neighborhood price
    # level (artifact-robust) next to the classic individual-price binning, plus
    # the Moran's-I map test. Feeds the report card and the Findings robustness
    # line, so those numbers regenerate with every retrain.
    from philly_fair_measure.diagnostics.equity_robustness import equity_robustness

    robustness = equity_robustness(root)

    evaluation = pl.read_parquet(run_dir / "evaluation.parquet")
    overall = evaluation.filter(
        (pl.col("segment_type") == "overall") & (pl.col("convention") == "out_of_time")
    )
    results_table = {
        str(r["model"]): {
            "rmse_log": round(float(r["rmse_log"]), 3),
            "mape_pct": round(float(r["mape"]) * 100, 1),
            "median_ratio": round(float(r["median_ratio"]), 3),
            "cod": round(float(r["cod"]), 1),
            "prd": round(float(r["prd"]), 3),
            "prb": round(float(r["prb"]), 3),
            "mki": round(float(r["mki"]), 3),
        }
        for r in overall.to_dicts()
    }

    # Condo out-of-time card (condo LightGBM vs OPA). The condo evaluation has
    # no convention column — it is out-of-time by construction.
    condo_overall = pl.read_parquet(latest_run_dir("condo", root) / "evaluation.parquet").filter(
        pl.col("segment_type") == "overall"
    )

    def _condo(model_name: str) -> dict[str, float]:
        r = condo_overall.filter(pl.col("model") == model_name).to_dicts()[0]
        return {
            "rmse_log": round(float(r["rmse_log"]), 3),
            "mape_pct": round(float(r["mape"]) * 100, 1),
            "median_ratio": round(float(r["median_ratio"]), 3),
            "cod": round(float(r["cod"]), 1),
            "prd": round(float(r["prd"]), 3),
            "prb": round(float(r["prb"]), 3),
        }

    condo_card = {"model": _condo("condo_lightgbm"), "opa": _condo("opa_assessment")}

    # The roll on display: assessments are certified the year before they take
    # effect, so the screen's valuation year + 1 is the tax year of the values
    # shown (valuation 2026 -> Tax Year 2027 roll).
    inferred_tax_year = int(np.max(screen_df["valuation_date"].dt.year().to_numpy())) + 1
    annual_settings = load_annual_report_settings(annual_report_config)
    tax_year = int(annual_settings["tax_year"])
    if tax_year != inferred_tax_year:
        raise ValueError(
            f"annual report config says tax year {tax_year}, but the assessment screen implies "
            f"{inferred_tax_year}"
        )

    # Release-day annual report.  Unlike the historical ratio cards above,
    # this compares the newly published roll with the last reassessment and
    # asks whether values moved toward the current independent estimate.  It is
    # explicitly provisional until post-effective-date sales exist.
    from philly_fair_measure.diagnostics.acs_sensitivity import _acs_frame, join_tracts
    from philly_fair_measure.diagnostics.annual_roll import (
        AnnualRollConfig,
        build_annual_roll_report,
    )

    locations = pl.read_parquet(
        root / "marts" / "assessment_features.parquet",
        columns=["parcel_id", "loc_lon", "loc_lat"],
    )
    race_context = join_tracts(locations, _acs_frame(root)).select("parcel_id", "acs_majority_race")

    annual_report = build_annual_roll_report(
        pl.read_parquet(root / "staged" / "assessments.parquet"),
        screen_df,
        AnnualRollConfig(
            tax_year=tax_year,
            comparison_year=int(annual_settings["comparison_year"]),
            effective_date=str(annual_settings["effective_date"]),
            sales_cutoff=str(annual_settings["sales_cutoff"]),
            status=str(annual_settings["status"]),
        ),
        locations=locations,
        demographics=race_context,
    )
    annual_report.update(
        {
            "benchmark_validation": _benchmark_validation(iaao_card),
            "opa_study_verdict": annual_settings["opa_study_verdict"],
            "appeal_deadlines": annual_settings["appeal_deadlines"],
            "sources": annual_settings["sources"],
        }
    )

    stats: dict[str, Any] = {
        "meta": {
            # This is a public, day-only "updated" label. Use Philadelphia's
            # calendar date so an evening export does not appear dated tomorrow.
            "generated_at": datetime.now(PHILADELPHIA_TZ).strftime("%Y-%m-%d"),
            "model_run_id": run_id,
            "interval_run_id": bayes_dir.name.removeprefix("run_id="),
            "n_test": int(ok.sum()),
            "n_sales_pool": sf.height,
            "tax_year": tax_year,
            "interval_nominal_pct": 90,
            "interval_coverage_pct": coverage_pct,
        },
        "full_card": full_card,
        "iaao_card": iaao_card,
        "condo_card": condo_card,
        "tiers_financed": tiers,
        "cash": {
            "share_all_pct": round(share_all * 100),
            "share_q1_pct": round(share_q1 * 100),
            "discount_pct": discount_pct,
        },
        "redistribution": redistribution,
        "tax_shift": tax_shift,
        "annual_report": annual_report,
        "equity_robustness": robustness,
        "screen": screen,
        "results_table": results_table,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stats, indent=2) + "\n")
    logger.info("web stats -> %s (run %s, n=%s)", out_path, run_id, joined.height)
    return stats
