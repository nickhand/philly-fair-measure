"""Fairness-robustness: is the race-gap elimination real, and how does it work?

Three measurements that move "8.7 -> 0.4 on one split" toward a defensible
claim, and pin down the mechanism.

1. mechanism_demo — train a deliberately COARSE model (hedonics + coarse
   categorical geography, no kNN sale surface / learned market areas / block
   rolls) alongside the RICH model, on the same sales. If the coarse model
   REPRODUCES a racial level gap while the rich one does not, the gap is a
   symptom of local-price under-fitting, not of demographics — direct proof of
   the mechanism (and a stress test: if the coarse model also closes the gap,
   our story is weaker and we'd say so).

2. race_gap_cv — re-run the by-race median-ratio gap in each temporal
   rolling-origin fold, so "0.4 points" becomes a distribution, not a lucky
   single split.

3. full_roll_fairness — score the ENTIRE residential roll (sold + unsold) and
   compare OPA value to the model's value by tract race. The sales-based
   fairness claim only holds for the ~5% that sell; this tests whether OPA's
   level bias is a full-roll phenomenon (the unsold-stock caveat).

Demographics are audit-only throughout. Diagnostics; nothing here feeds a
model or the screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config

logger = logging.getLogger(__name__)

# OPA-style pre-spatial-ML feature set: hedonics + condition + coarse
# categorical geography, WITHOUT the learned market areas, kNN sale surface,
# and block rolling means that carry local price level in the rich model.
COARSE_NUMERIC = [
    "char_livable_area", "char_lot_area", "char_beds", "char_baths",
    "char_year_built", "char_garage_spaces", "char_fireplaces",
]
COARSE_CATEGORICAL = [
    "char_style", "char_era", "char_exterior_condition", "char_interior_condition",
    "char_quality_grade_raw", "loc_zip5", "loc_ward",
]
_GROUPS = ("White alone", "Black alone", "Hispanic/Latino, any race")


def _by_race(df: pl.DataFrame, value: np.ndarray, price: np.ndarray) -> dict:
    from philly_assessments.models.metrics import evaluate_estimates

    maj = df["acs_majority_race"].fill_null("unmatched").to_numpy()
    out = {}
    for g in _GROUPS:
        m = (maj == g) & np.isfinite(value) & np.isfinite(price) & (value > 0) & (price > 0)
        if m.sum() >= 300:
            out[g] = evaluate_estimates(value[m], price[m])
    return out


def mechanism_demo(data_dir: Path | None = None) -> pl.DataFrame:
    from philly_assessments.diagnostics.acs_sensitivity import _acs_frame, join_tracts
    from philly_assessments.diagnostics.stability import _fit_predict
    from philly_assessments.models.baseline import _load_frame, feature_lists

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    n_test = max(1, int(df.height * 0.1))
    train, test = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(1, int(train.height * 0.1))
    fit_df, val_df = train.head(train.height - n_val), train.tail(n_val)

    rich_num, rich_cat = feature_lists(time_adjusted=True)
    preds = {
        "rich": _fit_predict(fit_df, val_df, test, rich_num, rich_cat),
        "coarse": _fit_predict(fit_df, val_df, test, COARSE_NUMERIC, COARSE_CATEGORICAL),
    }
    test = join_tracts(test, _acs_frame(data_dir))
    price = test["sale_price"].to_numpy()
    opa = test["asmt_market_value_sale_year"].to_numpy()

    rows = []
    for model, value in (("opa", opa), ("coarse_model", preds["coarse"]),
                         ("rich_model", preds["rich"])):
        stats = _by_race(test, value, price)
        for g, m in stats.items():
            rows.append({"model": model, "group": g,
                         "median_ratio": m["median_ratio"], "cod": m["cod"]})
    return pl.DataFrame(rows)


def race_gap_cv(data_dir: Path | None = None, *, n_folds: int = 5) -> pl.DataFrame:
    from philly_assessments.diagnostics.acs_sensitivity import _acs_frame, join_tracts
    from philly_assessments.diagnostics.stability import _fit_predict
    from philly_assessments.models.baseline import _load_frame, feature_lists

    root = data_dir if data_dir is not None else config.data_dir()
    df = _load_frame(root / "marts" / "sale_features.parquet")
    numeric, categorical = feature_lists(time_adjusted=True)
    acs = _acs_frame(data_dir)
    n = df.height
    fold = n // (2 * n_folds)

    rows = []
    for i in range(n_folds):
        stop = n - (n_folds - 1 - i) * fold
        test_df = df.slice(stop - fold, fold)
        train = df.head(stop - fold)
        n_val = max(1, int(train.height * 0.1))
        fit_df, val_df = train.head(train.height - n_val), train.tail(n_val)
        pred = _fit_predict(fit_df, val_df, test_df, numeric, categorical)
        tj = join_tracts(test_df, acs)
        price = tj["sale_price"].to_numpy()
        opa = tj["asmt_market_value_sale_year"].to_numpy()
        model_stats = _by_race(tj, pred, price)
        opa_stats = _by_race(tj, opa, price)

        def gap(stats):
            if "White alone" in stats and "Black alone" in stats:
                return stats["Black alone"]["median_ratio"] - stats["White alone"]["median_ratio"]
            return None

        rows.append({
            "fold": i + 1,
            "test_from": str(test_df["sale_date"].min())[:10],
            "opa_black_white_gap": gap(opa_stats),
            "model_black_white_gap": gap(model_stats),
        })
        logger.info("race-gap fold %d done", i + 1)
    return pl.DataFrame(rows)


def full_roll_fairness(data_dir: Path | None = None) -> pl.DataFrame:
    """OPA value vs model value by tract race on the FULL residential roll
    (sold + unsold), testing whether the level bias holds beyond sold sales."""
    from philly_assessments.diagnostics.acs_sensitivity import _acs_frame, join_tracts

    root = data_dir if data_dir is not None else config.data_dir()
    screen = pl.read_parquet(root / "marts" / "assessment_screen.parquet").filter(
        (pl.col("model_family") == "residential")
        & (pl.col("opa_market_value").fill_null(0) > 0)
        & (pl.col("model_median") > 0)
    )
    coords = pl.read_parquet(root / "marts" / "assessment_features.parquet").select(
        "parcel_id", "loc_lon", "loc_lat"
    )
    df = join_tracts(screen.join(coords, on="parcel_id", how="left"), _acs_frame(data_dir))
    opa = df["opa_market_value"].to_numpy()
    model = df["model_median"].to_numpy()
    maj = df["acs_majority_race"].fill_null("unmatched").to_numpy()

    rows = []
    for g in _GROUPS:
        m = maj == g
        if m.sum() < 300:
            continue
        rows.append({
            "group": g,
            "n_properties": int(m.sum()),
            "median_opa_over_model": float(np.median(opa[m] / model[m])),
            "share_opa_over_110pct": float((opa[m] / model[m] > 1.10).mean()),
        })
    return pl.DataFrame(rows)


@dataclass(frozen=True)
class FairnessRobustnessResult:
    mechanism: pl.DataFrame
    cv: pl.DataFrame
    full_roll: pl.DataFrame


def fairness_robustness(data_dir: Path | None = None) -> FairnessRobustnessResult:
    return FairnessRobustnessResult(
        mechanism=mechanism_demo(data_dir),
        cv=race_gap_cv(data_dir),
        full_roll=full_roll_fairness(data_dir),
    )
