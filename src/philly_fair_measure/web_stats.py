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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.metrics import evaluate_estimates
from philly_fair_measure.models.scoring import latest_run_dir

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("web/src/data/siteStats.json")


def _req(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"metric {name} is unexpectedly None — sample too small?")
    return value


def _card(estimate: np.ndarray, price: np.ndarray) -> dict[str, float]:
    m = evaluate_estimates(estimate, price)
    return {
        "median_ratio": round(_req(m.median_ratio, "median_ratio"), 3),
        "cod": round(_req(m.cod, "cod"), 1),
        "prd": round(_req(m.prd, "prd"), 3),
        "prb": round(_req(m.prb, "prb"), 3),
        "mape_pct": round(_req(m.mape, "mape") * 100, 1),
    }


def _iqr_trim_mask(ratio: np.ndarray) -> np.ndarray:
    """IAAO 3×IQR ratio trim — the same assesspy implementation the ratio-study
    bridge and the report card use, so the exported numbers match the docs."""
    from philly_fair_measure.diagnostics.ratio_study import _iaao_outlier_mask

    return np.asarray(~_iaao_outlier_mask(ratio))


def export_web_stats(data_dir: Path | None = None, out_path: Path = DEFAULT_OUT) -> dict[str, Any]:
    root = data_dir if data_dir is not None else config.data_dir()
    run_dir = latest_run_dir("baseline", root)
    run_id = run_dir.name.removeprefix("run_id=")

    preds = pl.read_parquet(run_dir / "predictions.parquet")
    sf = pl.read_parquet(root / "marts" / "sale_features.parquet")
    joined = preds.join(
        sf.select("sale_id", "time_adj_log", "fin_cash_sale"), on="sale_id", how="left"
    ).drop_nulls(["sale_price", "pred_lightgbm", "opa_assessment"])

    price = joined["sale_price"].to_numpy().astype(np.float64)
    model = joined["pred_lightgbm"].to_numpy().astype(np.float64)
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

    stats: dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "model_run_id": run_id,
            "interval_run_id": bayes_dir.name.removeprefix("run_id="),
            "n_test": int(ok.sum()),
            "interval_nominal_pct": 90,
            "interval_coverage_pct": coverage_pct,
        },
        "full_card": full_card,
        "iaao_card": iaao_card,
        "tiers_financed": tiers,
        "cash": {
            "share_all_pct": round(share_all * 100),
            "share_q1_pct": round(share_q1 * 100),
            "discount_pct": discount_pct,
        },
        "redistribution": redistribution,
        "screen": screen,
        "results_table": results_table,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stats, indent=2) + "\n")
    logger.info("web stats -> %s (run %s, n=%s)", out_path, run_id, joined.height)
    return stats
