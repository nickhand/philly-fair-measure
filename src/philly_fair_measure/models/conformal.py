"""Spatially weighted conformal intervals: a frequentist cross-check on the
Bayesian screen.

Split-conformal prediction wraps the LightGBM point model with intervals that
need only exchangeability of calibration residuals — no likelihood, no
hierarchy, no sampler. The Bayesian screen and this check therefore share
*nothing* except the feature mart: different model, different uncertainty
mechanism. Where both machines put OPA's value outside their 90% band, the
flag is robust to either method's assumptions.

Mechanics:

- The calibration set is a run's validation slice, rebuilt exactly from the
  mart + persisted split fractions (splits are deterministic: sort by
  sale_date/sale_id, then head/tail). Residuals are signed log residuals
  y − ŷ, which are frame-invariant (a time adjustment shifts target and
  prediction equally), so offsets computed here apply at any valuation date.
- Intervals are asymmetric: lower/upper offsets are separate finite-sample
  quantiles (the residual distribution is left-skewed in the cheap tail).
- Three weighting schemes:
    global    one offset pair for everyone
    district  Mondrian conformal by loc_district, min-n fallback to global
    knn       locally weighted: per-target quantiles of the k nearest
              calibration residuals in projected space with 1/(d+softening)
              weights and a (k+1)/k finite-sample level inflation — the
              "spatially weighted" variant, adapting to spatial
              heteroscedasticity the way the Bayesian sigma model does
- Honesty notes, in order of bite: (1) the validation slice also chose the
  early-stopping round and fit the isotonic calibration, so its residuals are
  slightly optimistic; (2) the split is time-ordered, so exchangeability is
  strained by market drift. Both are why `conformal_check` reports *realized*
  out-of-time test coverage next to the nominal level instead of trusting it.

The module is run-kind agnostic: it serves the residential cross-check and is
the interval engine for the condo screen (the condo model has no Bayesian arm).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.ingest.manifests import read_derived_manifest
from philly_fair_measure.models.scoring import latest_run_dir, run_params, score_lightgbm

logger = logging.getLogger(__name__)

ALPHA = 0.10
KNN_K = 500
SOFTENING_M = 250.0
MIN_GROUP = 200
_CHUNK = 25_000

_MART_BY_KIND = {"baseline": "sale_features", "condo": "condo_sale_features"}
# trainer defaults, for runs that predate persisting validation_fraction
_VAL_FRACTION_DEFAULT = {"baseline": 0.1, "condo": 0.15}


def run_kind(run_dir: Path) -> str:
    return run_dir.name.rsplit("-", 1)[-1]


def _load_mart_frame(kind: str, mart_path: Path) -> pl.DataFrame:
    if kind == "baseline":
        from philly_fair_measure.models.baseline import _load_frame

        return _load_frame(mart_path)
    df = pl.read_parquet(mart_path).sort("sale_date", "sale_id")
    if "time_adj_log" not in df.columns:
        df = df.with_columns(pl.lit(0.0).alias("time_adj_log"))
    return df


def split_frames(
    run_dir: Path, data_dir: Path | None = None
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """(fit, val, test) exactly as the trainer saw them."""
    root = data_dir if data_dir is not None else config.data_dir()
    kind = run_kind(run_dir)
    mart_path = root / "marts" / f"{_MART_BY_KIND[kind]}.parquet"
    if read_derived_manifest(run_dir / "run.parquet").built_at < (
        mart_built := read_derived_manifest(mart_path).built_at
    ):
        logger.warning(
            "%s predates the current %s mart (%s): splits may not match training",
            run_dir.name,
            mart_path.stem,
            mart_built,
        )
    params = run_params(run_dir)
    df = _load_mart_frame(kind, mart_path)
    n_test = max(1, int(df.height * params["test_fraction"]))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    n_val = max(
        1,
        int(train_df.height * params.get("validation_fraction", _VAL_FRACTION_DEFAULT[kind])),
    )
    val_df = train_df.tail(n_val)
    return train_df.head(train_df.height - n_val), val_df, test_df


def frame_residuals(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    """Signed log residuals y − ŷ (frame-invariant; see module docstring)."""
    pred_log = np.log(score_lightgbm(run_dir, df))
    y = np.log(df["sale_price"].to_numpy())
    if run_params(run_dir).get("time_adjusted"):
        # score_lightgbm already returns reference-frame estimates
        y = y + df["time_adj_log"].cast(pl.Float64).fill_null(0.0).to_numpy()
    return np.asarray(y - pred_log, dtype=np.float64)


def xy_district(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    from philly_fair_measure.features.market_areas import project_xy

    xy = df.select(*project_xy(pl.col("loc_lon"), pl.col("loc_lat"))).cast(pl.Float64).to_numpy()
    district = df["loc_district"].cast(pl.String).fill_null("").to_numpy()
    return xy, district


@dataclass(frozen=True)
class CalibrationSet:
    residual: np.ndarray  # signed log residuals on the validation slice
    xy: np.ndarray  # (n, 2) projected meters; NaN when unlocated
    district: np.ndarray  # string labels; "" when missing


def calibration_from_run(run_dir: Path, data_dir: Path | None = None) -> CalibrationSet:
    _, val_df, _ = split_frames(run_dir, data_dir)
    residual = frame_residuals(run_dir, val_df)
    xy, district = xy_district(val_df)
    ok = np.isfinite(residual)
    if not ok.all():
        logger.info("dropping %d calibration rows with non-finite residuals", int((~ok).sum()))
    return CalibrationSet(residual=residual[ok], xy=xy[ok], district=district[ok])


def _split_quantiles(residual: np.ndarray, alpha: float) -> tuple[float, float]:
    """Finite-sample-corrected (lo, hi) offsets from a plain residual sample."""
    r = np.sort(residual)
    n = len(r)
    if n == 0:
        return -np.inf, np.inf
    hi_ix = int(np.ceil((n + 1) * (1 - alpha / 2))) - 1
    lo_ix = n - 1 - hi_ix
    hi = float(r[hi_ix]) if hi_ix < n else np.inf
    lo = float(r[lo_ix]) if lo_ix >= 0 else -np.inf
    return lo, hi


def _weighted_upper(r: np.ndarray, w: np.ndarray, level: float) -> np.ndarray:
    """Row-wise weighted upper quantile of neighbor residuals."""
    order = np.argsort(r, axis=1)
    r_sorted = np.take_along_axis(r, order, axis=1)
    w_sorted = np.take_along_axis(w, order, axis=1)
    cum = np.cumsum(w_sorted, axis=1) / w_sorted.sum(axis=1)[:, None]
    reached = cum >= level
    ix = reached.argmax(axis=1)
    out = np.take_along_axis(r_sorted, ix[:, None], axis=1)[:, 0]
    # fp guard: cum[:, -1] can undershoot 1.0 by an ulp when level == 1.0
    return np.where(reached.any(axis=1), out, r_sorted[:, -1])


def conformal_offsets(
    cal: CalibrationSet,
    xy: np.ndarray,
    district: np.ndarray,
    *,
    alpha: float = ALPHA,
    method: str = "knn",
    k: int = KNN_K,
    softening_m: float = SOFTENING_M,
    min_group: int = MIN_GROUP,
    chunk_size: int = _CHUNK,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-row (lo, hi) log offsets; the price interval is exp(log_pred + lo/hi).

    Rows the method can't serve (missing coordinates, thin/unseen district)
    fall back to the global offsets.
    """
    n_rows = len(xy)
    g_lo, g_hi = _split_quantiles(cal.residual, alpha)
    lo = np.full(n_rows, g_lo)
    hi = np.full(n_rows, g_hi)
    if method == "global":
        return lo, hi
    if method == "district":
        table = {}
        for label in np.unique(cal.district):
            mask = cal.district == label
            if label and int(mask.sum()) >= min_group:
                table[str(label)] = _split_quantiles(cal.residual[mask], alpha)
        uniq, inverse = np.unique(district, return_inverse=True)
        pairs = np.array([table.get(str(u), (g_lo, g_hi)) for u in uniq])
        return pairs[inverse, 0], pairs[inverse, 1]
    if method != "knn":
        raise ValueError(f"unknown conformal method {method!r}")

    from scipy.spatial import cKDTree

    cal_ok = np.isfinite(cal.xy).all(axis=1)
    r_cal = cal.residual[cal_ok]
    tree = cKDTree(cal.xy[cal_ok])
    kk = min(k, tree.n)
    if kk == 0:
        return lo, hi
    targets = np.flatnonzero(np.isfinite(xy).all(axis=1))
    # finite-sample correction: the weighted analog of using the
    # ceil((k+1)(1-a/2))-th residual; always reachable, so offsets stay finite
    # (a self-mass-at-inf correction blows up where neighbors are far)
    level = min(1.0, (1 - alpha / 2) * (kk + 1) / kk)
    for start in range(0, len(targets), chunk_size):
        rows = targets[start : start + chunk_size]
        dist, ix = tree.query(xy[rows], k=kk, workers=-1)
        if kk == 1:
            dist, ix = dist[:, None], ix[:, None]
        r = r_cal[ix]
        w = 1.0 / (dist + softening_m)
        hi[rows] = _weighted_upper(r, w, level)
        lo[rows] = -_weighted_upper(-r, w, level)
    return lo, hi


@dataclass(frozen=True)
class ConformalCheckResult:
    run_dir: Path
    table: pl.DataFrame  # coverage/width by method × segment (bayesian included)
    district_coverage: pl.DataFrame
    flag_agreement: pl.DataFrame | None


def _segment_masks(test_df: pl.DataFrame, price: np.ndarray) -> list[tuple[str, str, np.ndarray]]:
    segments: list[tuple[str, str, np.ndarray]] = [
        ("overall", "overall", np.ones(test_df.height, dtype=bool))
    ]
    if "char_style" in test_df.columns:
        style = test_df["char_style"].cast(pl.String).fill_null("").to_numpy()
        for name in ("row", "twin", "detached"):
            segments.append(("style", name, style == name))
    edges = np.quantile(price, [0.2, 0.4, 0.6, 0.8])
    quintile = np.digitize(price, edges) + 1
    for q in range(1, 6):
        segments.append(("price_quintile", f"q{q}", quintile == q))
    return segments


def _screen_flag_agreement(
    screen_path: Path, features_path: Path, cal: CalibrationSet, *, alpha: float, k: int
) -> pl.DataFrame:
    screen = pl.read_parquet(screen_path)
    if "model_family" in screen.columns:
        screen = screen.filter(pl.col("model_family") == "residential")
    coords = pl.read_parquet(features_path).select(
        "parcel_id", "loc_lon", "loc_lat", "loc_district"
    )
    df = screen.join(coords, on="parcel_id", how="left")
    xy, district = xy_district(df)
    lo, hi = conformal_offsets(cal, xy, district, alpha=alpha, method="knn", k=k)
    # pred_lightgbm carries the isotonic calibration the residuals were
    # measured against (NOT the screen's extra median-ratio division)
    pred = df["pred_lightgbm"].to_numpy()
    opa = df["opa_market_value"].fill_null(0.0).to_numpy()
    conformal_flag = np.where(
        opa <= 0,
        "no_assessment",
        np.where(
            opa > pred * np.exp(hi),
            "over_assessed_candidate",
            np.where(opa < pred * np.exp(lo), "under_assessed_candidate", "within_range"),
        ),
    )
    return (
        df.select(pl.col("assessment_flag").alias("bayesian_flag"))
        .with_columns(pl.Series("conformal_flag", conformal_flag))
        .group_by("bayesian_flag", "conformal_flag")
        .len()
        .sort("bayesian_flag", "conformal_flag")
    )


def conformal_check(
    data_dir: Path | None = None,
    *,
    alpha: float = ALPHA,
    k: int = KNN_K,
    include_screen: bool = True,
) -> ConformalCheckResult:
    """Out-of-time coverage/width of conformal vs Bayesian intervals on the
    residential test slice, plus screen flag agreement. Persists artifacts
    into the baseline run directory."""
    root = data_dir if data_dir is not None else config.data_dir()
    run_dir = latest_run_dir("baseline", data_dir)
    _, val_df, test_df = split_frames(run_dir, data_dir)
    residual = frame_residuals(run_dir, val_df)
    xy_v, district_v = xy_district(val_df)
    ok = np.isfinite(residual)
    cal = CalibrationSet(residual=residual[ok], xy=xy_v[ok], district=district_v[ok])

    test_resid = frame_residuals(run_dir, test_df)
    xy_t, district_t = xy_district(test_df)
    price = test_df["sale_price"].to_numpy()

    covered: dict[str, np.ndarray] = {}
    width: dict[str, np.ndarray] = {}
    for name, method in (
        ("conformal_global", "global"),
        ("conformal_district", "district"),
        ("conformal_knn", "knn"),
    ):
        lo, hi = conformal_offsets(cal, xy_t, district_t, alpha=alpha, method=method, k=k)
        covered[name] = (test_resid >= lo) & (test_resid <= hi)
        width[name] = hi - lo

    bayes_run = latest_run_dir("bayesian", data_dir)
    from philly_fair_measure.models.scoring import score_bayesian_intervals

    _, b_lo, b_hi = score_bayesian_intervals(
        bayes_run, test_df, pi_low=alpha / 2, pi_high=1 - alpha / 2
    )
    covered["bayesian"] = (price >= b_lo) & (price <= b_hi)
    width["bayesian"] = np.log(b_hi / b_lo)

    rows = []
    for method_name in covered:
        for seg_type, seg, mask in _segment_masks(test_df, price):
            if not mask.any():
                continue
            rows.append(
                {
                    "method": method_name,
                    "segment_type": seg_type,
                    "segment": seg,
                    "n": int(mask.sum()),
                    "coverage": float(covered[method_name][mask].mean()),
                    "median_width_log": float(np.median(width[method_name][mask])),
                    "nominal": 1 - alpha,
                }
            )
    table = pl.DataFrame(rows)

    d_rows = []
    for method_name in covered:
        for label in np.unique(district_t):
            mask = district_t == label
            if not label or int(mask.sum()) < 100:
                continue
            d_rows.append(
                {
                    "method": method_name,
                    "district": str(label),
                    "n": int(mask.sum()),
                    "coverage": float(covered[method_name][mask].mean()),
                }
            )
    district_coverage = pl.DataFrame(d_rows)

    flag_agreement = None
    if include_screen:
        screen_path = root / "marts" / "assessment_screen.parquet"
        features_path = root / "marts" / "assessment_features.parquet"
        if screen_path.exists() and features_path.exists():
            flag_agreement = _screen_flag_agreement(
                screen_path, features_path, cal, alpha=alpha, k=k
            )
        else:
            logger.info("screen marts missing; skipping flag agreement")

    table.write_parquet(run_dir / "conformal_check.parquet")
    district_coverage.write_parquet(run_dir / "conformal_district_coverage.parquet")
    if flag_agreement is not None:
        flag_agreement.write_parquet(run_dir / "conformal_flag_agreement.parquet")
    return ConformalCheckResult(
        run_dir=run_dir,
        table=table,
        district_coverage=district_coverage,
        flag_agreement=flag_agreement,
    )
