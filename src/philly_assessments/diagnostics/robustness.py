"""Robustness audit: the two measurements a hostile reviewer would demand.

1. char_leakage_bound — the model uses TODAY's characteristics for every sale,
   so a house renovated between sale and now leaks future information. This
   bounds the effect: the out-of-time test set is recent (2025-2026 sales, so
   little elapsed time), and splitting it by whether any permit was issued
   AFTER the sale (the proxy for "the property changed") shows whether the
   model's advantage over OPA survives on the leakage-safe subset. If the edge
   holds where the property demonstrably did not change, leakage is not driving
   it — the answer becomes "measured", not "acknowledged".

2. racial_gap_conventions — the equity report's racial tables use actual sale
   prices (the blend convention). The rebuttal is "the Black/Hispanic-tract gap
   is just cash-sale composition." This re-runs the tract-race ratio study
   against retail-equivalent prices (cash sales marked up by the published
   per-tier channel discount), closing the same flank the price-quintile
   steelman closed.

Diagnostics only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RobustnessResult:
    char_leakage: pl.DataFrame
    racial_conventions: pl.DataFrame


def char_leakage_bound(data_dir: Path | None = None) -> pl.DataFrame:
    """Model vs OPA on leakage-safe (no post-sale permit) vs exposed subsets of
    the out-of-time test set."""
    from philly_assessments.models.metrics import evaluate_estimates
    from philly_assessments.models.scoring import latest_run_dir

    root = data_dir if data_dir is not None else config.data_dir()
    run = latest_run_dir("baseline", data_dir)
    pred = pl.read_parquet(run / "predictions.parquet")

    permits = (
        pl.scan_parquet(root / "staged" / "permits.parquet")
        .filter(
            pl.col("opa_account_num").is_not_null()
            & pl.col("permitissuedate_parsed").is_not_null()
        )
        .select(pl.col("opa_account_num").alias("parcel_id"), "permitissuedate_parsed")
        .collect()
    )
    post = (
        pred.select("sale_id", "parcel_id", "sale_date")
        .join(permits, on="parcel_id", how="left")
        .with_columns((pl.col("permitissuedate_parsed") > pl.col("sale_date")).alias("post"))
        .group_by("sale_id")
        .agg(pl.col("post").any().fill_null(False).alias("has_post_permit"))
    )
    pred = pred.join(post, on="sale_id", how="left").with_columns(
        pl.col("has_post_permit").fill_null(False)
    )

    price = pred["sale_price"].to_numpy()
    model = pred["pred_lightgbm"].to_numpy()
    opa = pred["opa_assessment"].to_numpy()
    safe = ~pred["has_post_permit"].to_numpy()

    rows = []
    for name, mask in (
        ("overall", np.ones(pred.height, bool)),
        ("leakage_safe (no post-sale permit)", safe),
        ("leakage_exposed (post-sale permit)", ~safe),
    ):
        m_model = evaluate_estimates(model[mask], price[mask])
        m_opa = evaluate_estimates(opa[mask], price[mask])
        edge = (
            m_opa.cod - m_model.cod
            if m_model.cod is not None and m_opa.cod is not None
            else None
        )
        rows.append(
            {
                "subset": name,
                "n": int(mask.sum()),
                "share": float(mask.mean()),
                "model_cod": m_model.cod,
                "model_ratio": m_model.median_ratio,
                "opa_cod": m_opa.cod,
                "opa_ratio": m_opa.median_ratio,
                "model_cod_edge": edge,
            }
        )
    return pl.DataFrame(rows)


def racial_gap_conventions(
    data_dir: Path | None = None, *, min_sale_year: int = 2023
) -> pl.DataFrame:
    """OPA ratio by tract majority race under cash vs retail value conventions."""
    from philly_assessments.diagnostics.acs_sensitivity import _acs_frame, join_tracts
    from philly_assessments.diagnostics.channel import (
        CHANNEL_DISCOUNT_BY_QUINTILE,
        sale_price_quintile_edges,
    )

    root = data_dir if data_dir is not None else config.data_dir()
    df = (
        pl.scan_parquet(root / "marts" / "sale_features.parquet")
        .filter(
            (pl.col("sale_year") >= min_sale_year)
            & pl.col("loc_lon").is_not_null()
            & (pl.col("sale_price") > 0)
            & (pl.col("asmt_market_value_sale_year").fill_null(0) > 0)
        )
        .select(
            "loc_lon", "loc_lat", "sale_price", "asmt_market_value_sale_year",
            "fin_cash_sale",
        )
        .collect()
    )
    df = join_tracts(df, _acs_frame(data_dir))

    price = df["sale_price"].to_numpy()
    opa = df["asmt_market_value_sale_year"].to_numpy()
    is_cash = (df["fin_cash_sale"].fill_null(1.0) == 1.0).to_numpy()
    edges = sale_price_quintile_edges(data_dir)
    quint = np.digitize(price, edges)  # 0..4
    disc = np.array(CHANNEL_DISCOUNT_BY_QUINTILE)[np.clip(quint, 0, 4)]
    retail_equiv = np.where(is_cash, price / (1.0 + disc), price)
    majority = df["acs_majority_race"].fill_null("unmatched").to_numpy()

    rows = []
    for group in ("White alone", "Black alone", "Hispanic/Latino, any race"):
        mask = majority == group
        if mask.sum() < 500:
            continue
        rows.append(
            {
                "group": group,
                "n": int(mask.sum()),
                "pct_cash": float(is_cash[mask].mean()),
                "opa_ratio_vs_sale_price": float(np.median(opa[mask] / price[mask])),
                "opa_ratio_vs_retail": float(np.median(opa[mask] / retail_equiv[mask])),
            }
        )
    return pl.DataFrame(rows)


def robustness_audit(data_dir: Path | None = None) -> RobustnessResult:
    return RobustnessResult(
        char_leakage=char_leakage_bound(data_dir),
        racial_conventions=racial_gap_conventions(data_dir),
    )
