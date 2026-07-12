"""IAAO-convention ratio study: the bridge from our honest metrics to OPA's
reported ones, plus sale-chasing checks.

OPA's TY2027 methodology reports COD 10.1 (external Keene study, TASP
convention, validated in-window sample) while we measure their roll at COD
~34 out-of-time. Neither number is wrong — they answer different questions.
`iaao_bridge` decomposes the gap by applying each convention change to BOTH
estimators (OPA's certified values and our model) on identical sales:

    out_of_time     certified/predicted value at the sale date vs the actual
                    later price — our headline convention (forecast question)
    time_adjusted   both sides moved to the index reference month (TASP);
                    removes market drift between valuation and sale
    in_window_model model refit WITH the evaluation sales in its training
                    data — what an assessor's model sees (OPA's values are
                    unchanged: their sales informed their roll by design)
    iaao_trimmed    3x IQR ratio outliers removed per estimator (IAAO
                    Standard on Ratio Studies, Appendix B) — sanctioned
                    curation, reported with the trim count
    by style        Keene reports singles/twins/rows separately

`sale_chasing_check` runs IAAO's sharpest "how did they do that" diagnostics:
assesspy's ratio-distribution heuristics, and the natural experiment Philly's
certification calendar provides — the same roll's ratio dispersion on sales
the assessor COULD have used (recorded before values were set) vs sales
recorded only after certification. Honest assessment quality looks the same
in both windows; sale-chasing (or in-sample overfit) shows up as markedly
tighter ratios on the pre-certification sales.

Diagnostics only: nothing here feeds models or the screen.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.metrics import evaluate_estimates

logger = logging.getLogger(__name__)

STYLES = ("detached", "twin", "row")


def _iaao_outlier_mask(ratio: np.ndarray) -> np.ndarray:
    """True where the ratio is a 3x-IQR outlier (IAAO standard trim)."""
    import assesspy

    return np.asarray(assesspy.is_outlier(ratio, method="iqr", mult=3.0).to_numpy(), dtype=bool)


def _rows(
    estimator: str,
    step: str,
    estimate: np.ndarray,
    price: np.ndarray,
    style: np.ndarray | None = None,
    *,
    trim: bool = False,
) -> list[dict]:
    ok = np.isfinite(estimate) & np.isfinite(price) & (estimate > 0) & (price > 0)
    estimate, price = estimate[ok], price[ok]
    style = style[ok] if style is not None else None
    n_trimmed = 0
    if trim:
        outlier = _iaao_outlier_mask(estimate / price)
        n_trimmed = int(outlier.sum())
        estimate, price = estimate[~outlier], price[~outlier]
        style = style[~outlier] if style is not None else None
    out = [
        {
            "estimator": estimator,
            "step": step,
            "segment": "overall",
            "n_trimmed": n_trimmed,
            **evaluate_estimates(estimate, price).as_row(),
        }
    ]
    if style is not None:
        for name in STYLES:
            mask = style == name
            if mask.sum() >= 50:
                out.append(
                    {
                        "estimator": estimator,
                        "step": step,
                        "segment": name,
                        "n_trimmed": n_trimmed,
                        **evaluate_estimates(estimate[mask], price[mask]).as_row(),
                    }
                )
    return out


def iaao_bridge(data_dir: Path | None = None) -> pl.DataFrame:
    """Convention ladder on the latest baseline run's out-of-time test slice."""
    import lightgbm as lgb

    from philly_fair_measure.models.baseline import (
        _encode,
        _fit_category_mappings,
        apply_vertical_calibration,
        fit_vertical_calibration,
    )
    from philly_fair_measure.models.conformal import split_frames
    from philly_fair_measure.models.scoring import latest_run_dir, run_params, score_point

    run_dir = latest_run_dir("baseline", data_dir)
    params = run_params(run_dir)
    fit_df, val_df, test_df = split_frames(run_dir, data_dir)

    price = test_df["sale_price"].to_numpy()
    adj = test_df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    price_tasp = price * np.exp(adj)
    style = test_df["char_style"].cast(pl.String).fill_null("").to_numpy()
    opa = test_df["asmt_market_value_sale_year"].cast(pl.Float64).to_numpy()

    pred_ref = np.log(score_point(run_dir, test_df))  # stacked + isotonic-calibrated, ref frame
    pred_at_date = np.exp(pred_ref - adj)

    # assessor-analog refit: identical features/params/capacity, but the
    # evaluation window is INSIDE the training data (like OPA's roll)
    numeric, categorical = params["numeric_features"], params["categorical_features"]
    full = pl.concat([fit_df, val_df, test_df], how="vertical")
    mappings = _fit_category_mappings(full, categorical)
    y_full = np.log(full["sale_price"].to_numpy())
    if params.get("time_adjusted"):
        y_full = y_full + full["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    logger.info(
        "in-window refit on %s sales (%s rounds)", f"{full.height:,}", params["best_iteration"]
    )
    booster = lgb.train(
        params["lgb_params"],
        lgb.Dataset(
            _encode(full, mappings, numeric, categorical),
            label=y_full,
            feature_name=numeric + categorical,
            categorical_feature=categorical,
        ),
        num_boost_round=params["best_iteration"],
    )
    x_val = _encode(val_df, mappings, numeric, categorical)
    x_test = _encode(test_df, mappings, numeric, categorical)
    y_val = np.log(val_df["sale_price"].to_numpy())
    if params.get("time_adjusted"):
        y_val = y_val + val_df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    calibration = fit_vertical_calibration(booster.predict(x_val), y_val)
    pred_in_ref = apply_vertical_calibration(booster.predict(x_test), calibration)

    # the roll Keene actually studied: the FRESH reassessment (latest published
    # tax year), which was fit with these very sales available — the OPA analog
    # of our in-window refit. The per-sale-year roll above is partly stale
    # carry-forward values.
    root = data_dir if data_dir is not None else config.data_dir()
    assessments = pl.scan_parquet(root / "staged" / "assessments.parquet")
    latest_year = assessments.select(pl.col("year_parsed").max()).collect().item()
    fresh = (
        assessments.filter(pl.col("year_parsed") == latest_year)
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("market_value").alias("fresh_value"),
        )
        .collect()
    )
    # join with an explicit row index and restore the original order: opa_fresh
    # is consumed as a parallel array against price_tasp/style pulled straight
    # from test_df, and polars left joins do not guarantee row order.
    opa_fresh = (
        test_df.select("parcel_id")
        .with_row_index("_row")
        .join(fresh, on="parcel_id", how="left")
        .sort("_row")["fresh_value"]
        .cast(pl.Float64)
        .to_numpy()
    )
    fresh_step = f"fresh_roll_ty{latest_year}"

    rows: list[dict] = []
    rows += _rows("opa", "out_of_time", opa, price)
    rows += _rows("model", "out_of_time", pred_at_date, price)
    rows += _rows("opa", "time_adjusted", opa, price_tasp)
    rows += _rows("model", "time_adjusted", np.exp(pred_ref), price_tasp)
    rows += _rows("opa", fresh_step, opa_fresh, price_tasp)
    rows += _rows("model", "in_window_model", np.exp(pred_in_ref), price_tasp)
    rows += _rows("opa", "iaao_trimmed", opa_fresh, price_tasp, style, trim=True)
    rows += _rows("model", "iaao_trimmed", np.exp(pred_in_ref), price_tasp, style, trim=True)
    return pl.DataFrame(rows)


def sale_chasing_check(
    data_dir: Path | None = None, *, roll_years: tuple[int, ...] = (2025, 2026)
) -> pl.DataFrame:
    """Same-roll ratio dispersion: sales the assessor could see vs couldn't.

    Philly certifies tax-year-T values in the spring of T-1, so calendar-year
    T-2 sales were available inputs while sales from July T-1 onward were
    recorded after certification. Both windows are compared against the SAME
    roll, time-adjusted, so market drift is removed and the only difference
    is whether the assessor could have seen the sale."""
    root = data_dir if data_dir is not None else config.data_dir()
    mart = pl.read_parquet(root / "marts" / "sale_features.parquet").select(
        "parcel_id", "sale_date", "sale_price", "time_adj_log", "char_style"
    )
    assessments = (
        pl.scan_parquet(root / "staged" / "assessments.parquet")
        .filter(pl.col("year_parsed").is_in(list(roll_years)))
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("year_parsed").alias("roll_year"),
            pl.col("market_value").alias("roll_value"),
        )
        .collect()
    )

    import assesspy

    rows = []
    for roll_year in roll_years:
        joined = mart.join(
            assessments.filter(pl.col("roll_year") == roll_year), on="parcel_id", how="inner"
        ).filter(pl.col("roll_value").fill_null(0) > 0)
        windows = {
            "before_certification": (
                pl.date(roll_year - 2, 1, 1),
                pl.date(roll_year - 2, 12, 31),
            ),
            "after_certification": (
                pl.date(roll_year - 1, 7, 1),
                pl.date(roll_year, 6, 30),
            ),
        }
        for window, (start, stop) in windows.items():
            sub = joined.filter(pl.col("sale_date").is_between(start, stop))
            if sub.height < 200:
                continue
            price_tasp = sub["sale_price"].to_numpy() * np.exp(
                sub["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
            )
            value = sub["roll_value"].cast(pl.Float64).to_numpy()
            ratio = value / price_tasp
            keep = ~_iaao_outlier_mask(ratio)
            chased = assesspy.is_sales_chased(ratio[keep].tolist())
            raw_ratio = value / sub["sale_price"].to_numpy()
            rows.append(
                {
                    "roll_year": roll_year,
                    "window": window,
                    **{
                        k: v
                        for k, v in evaluate_estimates(value[keep], price_tasp[keep])
                        .as_row()
                        .items()
                        if k in ("n", "median_ratio", "cod", "prd", "prb")
                    },
                    "pct_within_2pct_of_price": float((np.abs(raw_ratio - 1.0) <= 0.02).mean()),
                    "assesspy_chased": bool(chased),
                }
            )
    return pl.DataFrame(rows)
