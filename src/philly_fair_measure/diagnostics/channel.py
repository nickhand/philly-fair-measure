"""Cash/financed market-bifurcation decomposition (the retail-value diagnostic).

We measured that ~40% of Philadelphia arms-length sales are cash, trading at a
large within-district discount to financed sales. Two very different things
drive that gap, and assessment fairness depends on separating them:

  1. pure channel discount  the SAME house sells lower through the cash /
                            wholesale / investor channel than it would in a
                            typical-financing retail sale (assessments should
                            look through this — retail value is the standard)
  2. real value difference  cash sales are disproportionately distressed
                            (vacant, delinquent, unpermitted, poor condition)
                            houses that are genuinely worth less — a shell has
                            no retail buyer, so its low price is not a discount

This module decomposes the raw cash gap by sequentially adding controls to an
OLS of reference-frame log price:

    raw (district FE only) -> + house composition -> + distress signals

The residual `is_cash` coefficient after all controls is the PURE CHANNEL
discount — the delta a retail-value channel-adjustment would remove. The
attenuation from raw to pure tells you how much of the headline gap is real
value vs channel. An is_cash x distress interaction checks the key claim that
the cash discount shrinks for distressed houses (where the low price is value,
not channel). Reported overall and by price quintile (q1 is the equity tail).

Diagnostic only — no model or screen consumes it. Its output is the number
that makes the regressivity finding robust to the "cheap homes really do sell
for less" rebuttal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from philly_fair_measure import config

logger = logging.getLogger(__name__)

# Pure within-tier cash-channel discounts by price quintile, measured via
# `philly channel-decomp` (the "+distress" stage, 2026-07-04). Published, not
# a hidden propensity: cash-market value = retail value * (1 + discount). This
# is the transparent way to express the cash convention — a documented number
# an owner or a board can inspect, NOT a demographic proxy baked into a model.
CHANNEL_DISCOUNT_BY_QUINTILE: Final = (-0.216, -0.127, -0.088, -0.049, -0.027)


def sale_price_quintile_edges(data_dir: Path | None = None) -> list[float]:
    """The 20/40/60/80 sale-price cut points the discounts are keyed to."""
    root = data_dir if data_dir is not None else config.data_dir()
    price = (
        pl.scan_parquet(root / "marts" / "sale_features.parquet")
        .select("sale_price")
        .collect()["sale_price"]
        .to_numpy()
    )
    return [float(v) for v in np.quantile(price, [0.2, 0.4, 0.6, 0.8])]


def cash_market_value(retail_value: np.ndarray, edges: list[float]) -> np.ndarray:
    """Convert retail value to cash-market realizable value by applying the
    published per-tier channel discount (tier assigned by the retail value)."""
    quintile = np.digitize(retail_value, edges)  # 0..4
    discount = np.array(CHANNEL_DISCOUNT_BY_QUINTILE)[np.clip(quintile, 0, 4)]
    return np.asarray(retail_value * (1.0 + discount), dtype=np.float64)


_HEDONIC_NUMERIC = [
    "char_livable_area",  # logged below
    "char_beds",
    "char_baths",
    "char_year_built",
    "mkt_knn_log_ppsf",
    "mkt_area_level_log_ppsf",
]
_HEDONIC_CATEGORICAL = ["char_style", "char_exterior_condition", "char_interior_condition"]
_DISTRESS = [
    "dist_tax_delinquent",
    "dist_sheriff_sale",
    "evt_n_vacant_complaints_5y_before",
    "evt_n_unpermitted_work_complaints_5y_before",
    "evt_n_severe_violations_5y_before",
    "evt_n_open_severe_at_sale",
]


def _onehot(df: pl.DataFrame, column: str) -> np.ndarray:
    values = df[column].cast(pl.String).fill_null("__na__")
    levels = sorted(values.unique().to_list())[1:]  # drop first as reference
    return (
        np.column_stack([(values == lv).to_numpy().astype(float) for lv in levels])
        if levels
        else np.empty((df.height, 0))
    )


def _standardize(a: np.ndarray) -> np.ndarray:
    med = np.nanmedian(a, axis=0)
    a = np.where(np.isnan(a), med, a)
    mean, std = a.mean(axis=0), a.std(axis=0)
    std[std == 0] = 1.0
    return np.asarray((a - mean) / std, dtype=np.float64)


def _design(df: pl.DataFrame, stage: str) -> tuple[np.ndarray, int]:
    """(design matrix with is_cash as the LAST column, index of is_cash)."""
    blocks = [np.ones((df.height, 1))]  # intercept
    blocks.append(_onehot(df, "loc_district"))
    if stage in ("hedonic", "distress", "interaction"):
        num = df.select(
            pl.col("char_livable_area").log1p(),
            *[pl.col(c).cast(pl.Float64) for c in _HEDONIC_NUMERIC[1:]],
        ).to_numpy()
        blocks.append(_standardize(num))
        for c in _HEDONIC_CATEGORICAL:
            blocks.append(_onehot(df, c))
    distress_any = None
    if stage in ("distress", "interaction"):
        dist = df.select([pl.col(c).cast(pl.Float64).fill_null(0.0) for c in _DISTRESS]).to_numpy()
        blocks.append(_standardize(dist))
        distress_any = (dist.sum(axis=1) > 0).astype(float)
    is_cash = df["fin_cash_sale"].cast(pl.Float64).fill_null(0.0).to_numpy()
    blocks.append(is_cash[:, None])
    cash_ix = sum(b.shape[1] for b in blocks) - 1
    if stage == "interaction" and distress_any is not None:
        blocks.append((is_cash * distress_any)[:, None])  # cash x distress
    return np.column_stack(blocks), cash_ix


def _ols_coef(x: np.ndarray, y: np.ndarray, ix: int | list[int]) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return np.asarray(beta[ix], dtype=np.float64)


@dataclass(frozen=True)
class ChannelResult:
    table: pl.DataFrame  # stage-by-stage cash discount, overall + by quintile
    interaction: dict


def channel_decomposition(
    data_dir: Path | None = None, *, n_boot: int = 200, seed: int = 42
) -> ChannelResult:
    from philly_fair_measure.models.baseline import _load_frame

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet").filter(
        pl.col("loc_district").is_not_null() & (pl.col("sale_price") > 0)
    )
    y = np.log(df["sale_price"].to_numpy()) + df["time_adj_log"].to_numpy()

    def pct(beta: float) -> float:
        return float(np.exp(beta) - 1.0)

    stages = ["raw", "hedonic", "distress"]
    price = df["sale_price"].to_numpy()
    edges = np.quantile(price, [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(price, edges) + 1
    rng = np.random.default_rng(seed)

    rows = []
    for segment, mask in [("overall", np.ones(df.height, bool))] + [
        (f"q{q}", quintile == q) for q in range(1, 6)
    ]:
        sub = df.filter(pl.Series(mask))
        y_sub = y[mask]
        for stage in stages:
            x, cash_ix = _design(sub, stage)
            beta = float(_ols_coef(x, y_sub, cash_ix))
            ci = None
            if segment == "overall":
                boots = np.empty(n_boot)
                n = len(y_sub)
                for b in range(n_boot):
                    idx = rng.integers(0, n, n)
                    boots[b] = _ols_coef(x[idx], y_sub[idx], cash_ix)
                ci = (pct(np.quantile(boots, 0.025)), pct(np.quantile(boots, 0.975)))
            rows.append(
                {
                    "segment": segment,
                    "stage": stage,
                    "cash_discount_pct": pct(beta),
                    "ci_low": ci[0] if ci else None,
                    "ci_high": ci[1] if ci else None,
                    "n": int(mask.sum()),
                }
            )

    # interaction: cash discount for non-distressed vs distressed houses
    x_int, cash_ix = _design(df, "interaction")
    betas = _ols_coef(x_int, y, [cash_ix, x_int.shape[1] - 1])
    interaction = {
        "cash_discount_clean_pct": pct(float(betas[0])),
        "cash_x_distress_pct_points": pct(float(betas[0] + betas[1])) - pct(float(betas[0])),
        "cash_discount_distressed_pct": pct(float(betas[0] + betas[1])),
    }

    table = pl.DataFrame(rows)
    from philly_fair_measure.ingest.derived import write_derived_table

    write_derived_table(
        table,
        root,
        "diagnostics",
        "channel_decomposition",
        [],
        notes="cash-vs-financed discount by control stage; retail-value diagnostic",
    )
    logger.info("channel decomposition: %s", interaction)
    return ChannelResult(table=table, interaction=interaction)
