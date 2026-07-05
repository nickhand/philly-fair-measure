"""Retail-market model: predicting typical-financing value, both conventions.

The cash/financed decomposition (diagnostics/channel.py) showed ~40% of sales
are cash at a large, distress-independent channel discount. Assessment law
targets *typical-financing (retail) market value*, so this trains a retail
predictor by restricting the training target to mortgage-financed arms-length
sales — the transactions that ARE the retail standard. Financed sales have
adequate geographic support (measured 2026-07-04: only 8 of 351 market areas
thin), and the location features (kNN surface, block rolls) are built from ALL
sales, so the model still sees the full market on the feature side while
targeting the retail price level.

`retail_vs_blend` trains the current blend model and the financed-only retail
model with identical features/params on the same split, then reports both on
the test set, broken out by transaction channel and price quintile. The
retail model should (a) match the blend model on financed test sales and
(b) predict ABOVE cash sale prices by roughly the channel discount — i.e.
recover retail value for houses that transacted wholesale. It also re-expresses
the OPA ratio study under both value conventions (against actual sale prices
vs against retail-equivalent prices), the number that makes the regressivity
finding robust.

Diagnostic: measures whether financed-only training is a sound retail predictor
before it is wired into the screen / appeal reports.
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
class RetailResult:
    model_table: pl.DataFrame  # blend vs retail, by channel/quintile
    opa_convention_table: pl.DataFrame  # OPA ratio under cash vs retail convention


def _train_predict(
    fit_df: pl.DataFrame,
    val_df: pl.DataFrame,
    test_df: pl.DataFrame,
    numeric: list[str],
    categorical: list[str],
) -> np.ndarray:
    import lightgbm as lgb

    from philly_assessments.models.baseline import (
        DEFAULT_LGB_PARAMS,
        _encode,
        _fit_category_mappings,
        apply_vertical_calibration,
        fit_vertical_calibration,
    )

    mappings = _fit_category_mappings(fit_df, categorical)

    def target(frame: pl.DataFrame) -> np.ndarray:
        y = np.log(frame["sale_price"].to_numpy()) + frame["time_adj_log"].to_numpy()
        return np.asarray(y, dtype=np.float64)

    x_fit = _encode(fit_df, mappings, numeric, categorical)
    x_val = _encode(val_df, mappings, numeric, categorical)
    x_test = _encode(test_df, mappings, numeric, categorical)
    train_set = lgb.Dataset(
        x_fit,
        label=target(fit_df),
        feature_name=numeric + categorical,
        categorical_feature=categorical,
    )
    booster = lgb.train(
        DEFAULT_LGB_PARAMS,
        train_set,
        num_boost_round=5000,
        valid_sets=[train_set.create_valid(x_val, label=target(val_df))],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    calibration = fit_vertical_calibration(
        booster.predict(x_val, num_iteration=booster.best_iteration), target(val_df)
    )
    pred_ref = apply_vertical_calibration(
        booster.predict(x_test, num_iteration=booster.best_iteration), calibration
    )
    return np.asarray(np.exp(pred_ref - test_df["time_adj_log"].to_numpy()), dtype=np.float64)


def retail_vs_blend(data_dir: Path | None = None) -> RetailResult:
    from philly_assessments.diagnostics.channel import channel_decomposition
    from philly_assessments.models.baseline import _load_frame, feature_lists
    from philly_assessments.models.metrics import evaluate_estimates

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    numeric, categorical = feature_lists(time_adjusted=True)

    n_test = max(1, int(df.height * 0.1))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train_df.height * 0.1))
    fit_df, val_df = train_df.head(train_df.height - n_val), train_df.tail(n_val)
    financed = pl.col("fin_cash_sale").fill_null(1.0) == 0.0

    pred_blend = _train_predict(fit_df, val_df, test_df, numeric, categorical)
    pred_retail = _train_predict(
        fit_df.filter(financed), val_df.filter(financed), test_df, numeric, categorical
    )

    price = test_df["sale_price"].to_numpy()
    is_cash = (test_df["fin_cash_sale"].fill_null(1.0) == 1.0).to_numpy()
    edges = np.quantile(price, [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(price, edges) + 1
    segments = [
        ("overall", np.ones(test_df.height, bool)),
        ("financed_sales", ~is_cash),
        ("cash_sales", is_cash),
    ]
    segments += [(f"q{q}", quintile == q) for q in range(1, 6)]

    rows = []
    for name, mask in segments:
        for model, pred in (("blend", pred_blend), ("retail", pred_retail)):
            rows.append(
                {
                    "segment": name,
                    "model": model,
                    **evaluate_estimates(pred[mask], price[mask]).as_row(),
                }
            )
    model_table = pl.DataFrame(rows)

    # OPA ratio study under both value conventions: actual sale price vs
    # retail-equivalent (cash sales marked up by the measured per-quintile
    # pure channel discount from the decomposition)
    decomp = channel_decomposition(data_dir).table
    disc = {
        r["segment"]: r["cash_discount_pct"]
        for r in decomp.filter(pl.col("stage") == "distress").to_dicts()
    }
    opa = test_df["asmt_market_value_sale_year"].to_numpy()
    retail_equiv = price.copy().astype(float)
    for q in range(1, 6):
        m = (quintile == q) & is_cash
        retail_equiv[m] = price[m] / (1.0 + disc.get(f"q{q}", 0.0))

    conv_rows = []
    for q in range(1, 6):
        m = quintile == q
        ok = m & np.isfinite(opa) & (opa > 0)
        conv_rows.append(
            {
                "quintile": f"q{q}",
                "n": int(m.sum()),
                "pct_cash": float(is_cash[m].mean()),
                "opa_ratio_vs_sale_price": float(np.median(opa[ok] / price[ok])),
                "opa_ratio_vs_retail": float(np.median(opa[ok] / retail_equiv[ok])),
            }
        )
    opa_convention_table = pl.DataFrame(conv_rows)

    from philly_assessments.ingest.derived import write_derived_table

    write_derived_table(
        model_table,
        root,
        "diagnostics",
        "retail_vs_blend",
        [],
        notes="blend vs financed-only retail model on the test set",
    )
    return RetailResult(model_table=model_table, opa_convention_table=opa_convention_table)
