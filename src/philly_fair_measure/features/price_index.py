"""Constant-quality price index (repeat sales) + market-area drift.

OPA calibrates every sale to the valuation date with a compound monthly index
and then drops time from its models; our v1 models carried time features and
visibly mis-extrapolated (docs/feature-plan-v2.md §1.1). The v1 index here was
a median log-$/sqft level per district — a MIX index: in gentrifying districts
the sale mix (gut renovations, new construction) drifts upscale, so the index
overstates what an unchanged house appreciated. Measured 2026-07-06 against
36,552 recent repeat pairs: per-district misstatement of constant-quality
appreciation ran −26% to +28%, and it flipped sign WITHIN a district (d_10
+15% overall while its market area ma_146 ran −11%) — inflating the
repeat-sale carry-forward feature by ~$100k+ on specific homes (2314 Wallace
St) and every comp's "adjusted today" price with it.

v2 (this module) is constant-quality by construction:

- **District curves — BMN repeat-sales regression** (Bailey–Muth–Nourse):
  quarterly dummies fit to Δlog(price) of same-parcel arms-length pairs,
  ridge-shrunk toward the citywide curve where districts are thin, then
  interpolated to months, 3-month smoothed, normalized so the latest month
  is 0. Pair hygiene: held ≥ ~6 months, |annualized Δlog| ≤ 0.35 (drops
  flips/gut renovations — those pairs are quality CHANGES, not appreciation).
- **Market-area drift** (`marts/area_drift.parquet`): per-area residual
  appreciation rate vs its district curve, δ_a = Σ(r·h)/(Σh² + K) over the
  area's pairs (r = pair residual, h = years held) — a shrunken
  constant-drift correction at the geography where the mix problem actually
  lives. Unknown areas get 0.

The special district ``__city__`` carries the citywide curve and is the
fallback for parcels without a district. Fixtures with too few repeat pairs
fall back to the v1 median-ppsf construction automatically (drift empty).

`with_time_adjustment` attaches ``time_adj_log`` = −log_index(district,
month) + δ_area·years_before_ref: adding it to log(price) expresses the sale
in reference-month dollars; models trained on adjusted prices predict at
reference level, and predictions are moved back to any date by subtracting
the adjustment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import overload

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.features.market_areas import sale_points
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest

logger = logging.getLogger(__name__)

SHRINKAGE_LAMBDA = 15.0
SMOOTH_MONTHS = 3
CITYWIDE = "__city__"

# repeat-sales machinery (v2 constant-quality index)
MIN_PAIRS_FOR_BMN = 500  # below this (unit fixtures), fall back to median-ppsf
PAIR_MIN_HELD_YEARS = 0.49
PAIR_MAX_ANNUAL_LOG = 0.35  # flips/gut renos are quality changes, not appreciation
PAIR_FLOOR_PRICE = 10_000.0
BMN_START = "1997-01-01"  # RTT records begin; earlier dates are parse garbage
RIDGE_TAU = 25.0  # pull district quarter effects toward the citywide curve
DRIFT_SHRINK_K = 200.0  # yr²; ~8 five-year pairs reach half-weight


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest
    drift_path: Path | None = None


def _repeat_pairs(sales: pl.LazyFrame) -> pl.DataFrame:
    """Same-parcel consecutive arms-length pairs with standard repeat-sales
    hygiene. Condo units are INCLUDED — a unit resold is the cleanest
    constant-quality observation there is, area fields notwithstanding."""
    s = (
        sales.filter(
            (pl.col("validity_status") == "arms_length")
            & pl.col("sale_date").is_not_null()
            & (pl.col("sale_price") > PAIR_FLOOR_PRICE)
        )
        .select("parcel_id", "sale_date", "sale_price")
        .collect()
        .sort("parcel_id", "sale_date")
        .with_columns(
            pl.col("sale_date").shift(1).over("parcel_id").alias("prev_date"),
            pl.col("sale_price").shift(1).over("parcel_id").alias("prev_price"),
        )
        .filter(pl.col("prev_date").is_not_null())
        .with_columns(
            ((pl.col("sale_date") - pl.col("prev_date")).dt.total_days() / 365.25).alias(
                "held_yrs"
            ),
            (pl.col("sale_price") / pl.col("prev_price")).log().alias("dlog"),
        )
        .filter(
            (pl.col("held_yrs") >= PAIR_MIN_HELD_YEARS)
            & ((pl.col("dlog") / pl.col("held_yrs")).abs() <= PAIR_MAX_ANNUAL_LOG)
            & (pl.col("prev_date") >= pl.lit(BMN_START).str.to_date())
        )
    )
    return s.select("parcel_id", "prev_date", "sale_date", "prev_price", "dlog", "held_yrs")


def _quarter_ix(dates: np.ndarray, q0_year: int) -> np.ndarray:
    """0-based quarter index from the BMN start year."""
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    months = dates.astype("datetime64[M]").astype(int) % 12
    return np.asarray((years - q0_year) * 4 + months // 3, dtype=np.int64)


def _bmn_curve(
    q1: np.ndarray, q2: np.ndarray, dlog: np.ndarray, n_quarters: int, prior: np.ndarray | None
) -> np.ndarray:
    """Quarterly log-level curve from pair data: least squares on ±1 quarter
    dummies (quarter 0 pinned to 0), optionally ridge-pulled toward a prior
    curve (the citywide one) so thin districts stay sane."""
    rows = np.arange(len(dlog))
    a = np.zeros((len(dlog), n_quarters - 1))
    for q, sign in ((q2, 1.0), (q1, -1.0)):
        mask = q > 0
        a[rows[mask], q[mask] - 1] += sign
    y = dlog.copy()
    if prior is not None:
        tau = np.sqrt(RIDGE_TAU)
        a = np.vstack([a, tau * np.eye(n_quarters - 1)])
        y = np.concatenate([y, tau * prior[1:]])
    beta, *_ = np.linalg.lstsq(a, y, rcond=None)
    curve = np.concatenate([[0.0], beta])
    # a quarter no pair touches has an all-zero column and lstsq leaves it at
    # 0 — if that's the LATEST quarter, normalization would anchor the whole
    # index to garbage. Carry the last supported level forward instead.
    if prior is None:
        supported = np.zeros(n_quarters, dtype=bool)
        supported[0] = True
        supported[np.unique(q1)] = True
        supported[np.unique(q2)] = True
        for qi in range(1, n_quarters):
            if not supported[qi]:
                curve[qi] = curve[qi - 1]
    return curve


def build_price_index(data_dir: Path | None = None) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    paths = {
        "opa": root / "staged" / "opa_properties.parquet",
        "sales": root / "marts" / "sale_validity.parquet",
        "market_areas": root / "marts" / "market_areas.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `fair-measure build-market-areas` first")

    points = sale_points(pl.scan_parquet(paths["sales"]), pl.scan_parquet(paths["opa"]))
    districts = pl.read_parquet(paths["market_areas"]).select("parcel_id", "district")
    points = points.join(districts, on="parcel_id", how="left").with_columns(
        pl.col("district").fill_null(CITYWIDE)
    )

    pairs = _repeat_pairs(pl.scan_parquet(paths["sales"]))
    if pairs.height >= MIN_PAIRS_FOR_BMN:
        return _build_repeat_sales(root, paths, points, pairs)
    logger.info("only %d repeat pairs — falling back to the median-ppsf index", pairs.height)

    citywide = points.group_by("month").agg(
        pl.col("log_ppsf").median().alias("city_med"), pl.len().alias("city_n")
    )
    by_district = points.group_by("district", "month").agg(
        pl.col("log_ppsf").median().alias("district_med"), pl.len().alias("n_sales")
    )

    # complete (district x month) grid so every month has an index value;
    # CITYWIDE is appended separately below, so keep it out of the grid
    months = citywide.select("month").sort("month")
    district_names = [d for d in points["district"].unique().to_list() if d != CITYWIDE]
    grid = months.join(pl.DataFrame({"district": district_names}), how="cross")

    raw = (
        grid.join(by_district, on=["district", "month"], how="left")
        .join(citywide, on="month", how="left")
        .with_columns(
            pl.col("n_sales").fill_null(0),
            pl.col("district_med").fill_null(pl.col("city_med")),
        )
        .with_columns(
            (
                (pl.col("n_sales") * pl.col("district_med") + SHRINKAGE_LAMBDA * pl.col("city_med"))
                / (pl.col("n_sales") + SHRINKAGE_LAMBDA)
            ).alias("shrunk")
        )
    )
    citywide_rows = citywide.sort("month").select(
        pl.lit(CITYWIDE).alias("district"),
        "month",
        pl.col("city_med").alias("shrunk"),
        pl.col("city_n").alias("n_sales"),
        "city_med",
    )
    raw = pl.concat(
        [raw.select("district", "month", "shrunk", "n_sales", "city_med"), citywide_rows]
    )

    smoothed = raw.sort("district", "month").with_columns(
        pl.col("shrunk")
        .rolling_mean(window_size=SMOOTH_MONTHS, center=True, min_samples=1)
        .over("district")
        .alias("level")
    )
    reference = smoothed.group_by("district").agg(
        pl.col("level").sort_by("month").last().alias("ref_level"),
        pl.col("month").max().alias("ref_month"),
    )
    index = (
        smoothed.join(reference, on="district")
        .with_columns((pl.col("level") - pl.col("ref_level")).alias("log_index"))
        .select("district", "month", "log_index", "n_sales", "ref_month")
        .sort("district", "month")
    )

    inputs = []
    for path in paths.values():
        manifest = read_derived_manifest(path)
        inputs.append(
            InputRef(
                dataset=f"{manifest.layer}/{manifest.table}",
                fetched_at=manifest.built_at.isoformat(),
            )
        )
    path, manifest = write_derived_table(
        index,
        root,
        "marts",
        "price_index",
        inputs,
        notes=f"median-ppsf fallback; lambda={SHRINKAGE_LAMBDA} smooth={SMOOTH_MONTHS}mo; "
        f"log_index normalized to 0 at the latest month; {CITYWIDE} = fallback",
    )
    drift_path, _ = write_derived_table(
        _empty_drift(),
        root,
        "marts",
        "area_drift",
        inputs,
        notes="empty (median-ppsf fallback index carries no area drift)",
    )
    return BuildResult(path=path, manifest=manifest, drift_path=drift_path)


def _empty_drift() -> pl.DataFrame:
    return pl.DataFrame(
        schema={"market_area": pl.String, "drift_per_yr": pl.Float64, "n_pairs": pl.Int64}
    )


def _build_repeat_sales(
    root: Path, paths: dict[str, Path], points: pl.DataFrame, pairs: pl.DataFrame
) -> BuildResult:
    """The v2 constant-quality build: BMN district curves + area drift."""
    ma = pl.read_parquet(paths["market_areas"]).select("parcel_id", "market_area", "district")
    pairs = pairs.join(ma, on="parcel_id", how="left").with_columns(
        pl.col("district").fill_null(CITYWIDE)
    )

    # month grid clamped to the BMN span: sale dates carry parse garbage
    # (a year-206 deed exists) and the curve can't speak before its pairs;
    # with_time_adjustment clamps out-of-range dates to the grid edges anyway
    months = (
        points.select("month")
        .unique()
        .filter(pl.col("month") >= pl.lit(BMN_START).str.to_date())
        .sort("month")["month"]
    )
    q0_year = int(BMN_START[:4])
    month_np = months.to_numpy().astype("datetime64[D]")
    month_q = np.clip(_quarter_ix(month_np, q0_year), 0, None)
    n_quarters = int(month_q.max()) + 1

    q1 = np.clip(
        _quarter_ix(pairs["prev_date"].to_numpy().astype("datetime64[D]"), q0_year),
        0,
        n_quarters - 1,
    )
    q2 = np.clip(
        _quarter_ix(pairs["sale_date"].to_numpy().astype("datetime64[D]"), q0_year),
        0,
        n_quarters - 1,
    )
    dlog = pairs["dlog"].to_numpy().astype(np.float64)
    district_arr = pairs["district"].to_numpy()

    city_curve = _bmn_curve(q1, q2, dlog, n_quarters, prior=None)
    district_names = [d for d in points["district"].unique().to_list() if d != CITYWIDE]
    curves: dict[str, np.ndarray] = {CITYWIDE: city_curve}
    for name in district_names:
        mask = district_arr == name
        if int(mask.sum()) == 0:
            curves[name] = city_curve
            continue
        curves[name] = _bmn_curve(q1[mask], q2[mask], dlog[mask], n_quarters, prior=city_curve)
        logger.info("BMN %s: %d pairs", name, int(mask.sum()))

    # pair residuals vs the district curve -> shrunken per-area drift rate
    lvl2 = np.array([curves[d][q] for d, q in zip(district_arr, q2, strict=True)])
    lvl1 = np.array([curves[d][q] for d, q in zip(district_arr, q1, strict=True)])
    resid = dlog - (lvl2 - lvl1)
    drift = (
        pairs.with_columns(pl.Series("resid", resid))
        .filter(pl.col("market_area").is_not_null())
        .group_by("market_area")
        .agg(
            (
                (pl.col("resid") * pl.col("held_yrs")).sum()
                / ((pl.col("held_yrs") ** 2).sum() + DRIFT_SHRINK_K)
            ).alias("drift_per_yr"),
            pl.len().alias("n_pairs"),
        )
        .sort("market_area")
    )

    # quarterly curves -> the monthly index table (same schema as v1)
    n_sales = (
        points.group_by("district", "month").agg(pl.len().alias("n_sales"))
        if "district" in points.columns
        else pl.DataFrame(schema={"district": pl.String, "month": pl.Date, "n_sales": pl.UInt32})
    )
    frames = []
    for name, curve in curves.items():
        levels = curve[month_q]
        frames.append(
            pl.DataFrame({"district": name, "month": months, "level": levels.astype(np.float64)})
        )
    smoothed = (
        pl.concat(frames)
        .sort("district", "month")
        .with_columns(
            pl.col("level")
            .rolling_mean(window_size=SMOOTH_MONTHS, center=True, min_samples=1)
            .over("district")
            .alias("level")
        )
    )
    reference = smoothed.group_by("district").agg(
        pl.col("level").sort_by("month").last().alias("ref_level"),
        pl.col("month").max().alias("ref_month"),
    )
    index = (
        smoothed.join(reference, on="district")
        .with_columns((pl.col("level") - pl.col("ref_level")).alias("log_index"))
        .join(n_sales, on=["district", "month"], how="left")
        .with_columns(pl.col("n_sales").fill_null(0))
        .select("district", "month", "log_index", "n_sales", "ref_month")
        .sort("district", "month")
    )

    inputs = []
    for path in paths.values():
        manifest = read_derived_manifest(path)
        inputs.append(
            InputRef(
                dataset=f"{manifest.layer}/{manifest.table}",
                fetched_at=manifest.built_at.isoformat(),
            )
        )
    path, manifest = write_derived_table(
        index,
        root,
        "marts",
        "price_index",
        inputs,
        notes=f"BMN repeat-sales, {pairs.height} pairs, tau={RIDGE_TAU}, "
        f"smooth={SMOOTH_MONTHS}mo; log_index normalized to 0 at the latest month; "
        f"{CITYWIDE} = fallback",
    )
    drift_path, _ = write_derived_table(
        drift,
        root,
        "marts",
        "area_drift",
        inputs,
        notes=f"per-market-area residual appreciation vs district BMN curve; "
        f"shrinkage K={DRIFT_SHRINK_K} yr^2",
    )
    logger.info(
        "repeat-sales index: %d pairs, %d districts; drift for %d areas",
        pairs.height,
        len(curves) - 1,
        drift.height,
    )
    return BuildResult(path=path, manifest=manifest, drift_path=drift_path)


@overload
def with_time_adjustment(
    lf: pl.DataFrame,
    index: pl.DataFrame,
    *,
    area_drift: pl.DataFrame | None = ...,
    district_col: str = ...,
    area_col: str = ...,
    date_col: str = ...,
    out_col: str = ...,
) -> pl.DataFrame: ...


@overload
def with_time_adjustment(
    lf: pl.LazyFrame,
    index: pl.DataFrame,
    *,
    area_drift: pl.DataFrame | None = ...,
    district_col: str = ...,
    area_col: str = ...,
    date_col: str = ...,
    out_col: str = ...,
) -> pl.LazyFrame: ...


def with_time_adjustment(
    lf: pl.LazyFrame | pl.DataFrame,
    index: pl.DataFrame,
    *,
    area_drift: pl.DataFrame | None = None,
    district_col: str = "loc_district",
    area_col: str = "loc_market_area",
    date_col: str = "sale_date",
    out_col: str = "time_adj_log",
) -> pl.LazyFrame | pl.DataFrame:
    """Attach ``out_col`` = −log_index(district, month(date)) +
    δ_area·years_before_ref, clamped to the index's month range; falls back to
    the citywide index for unknown districts and δ=0 for unknown areas (or
    when no drift table is passed). A DataFrame in gives a DataFrame back; a
    LazyFrame stays lazy."""
    bounds = index.select(pl.col("month").min().alias("lo"), pl.col("month").max().alias("hi"))
    lo, hi = bounds.row(0)
    city = index.filter(pl.col("district") == CITYWIDE).select(
        "month", pl.col("log_index").alias("_city_index")
    )
    district_index = index.select("district", "month", pl.col("log_index").alias("_d_index"))

    out = (
        lf.lazy()
        .with_columns(
            pl.col(date_col).dt.truncate("1mo").clip(pl.lit(lo), pl.lit(hi)).alias("_adj_month"),
            pl.col(district_col).fill_null(CITYWIDE).alias("_adj_district"),
        )
        .join(
            district_index.lazy(),
            left_on=["_adj_district", "_adj_month"],
            right_on=["district", "month"],
            how="left",
        )
        .join(
            city.lazy(),
            left_on="_adj_month",
            right_on="month",
            how="left",
        )
        .with_columns((-pl.coalesce("_d_index", "_city_index").fill_null(0.0)).alias(out_col))
    )
    schema = lf.collect_schema().names() if isinstance(lf, pl.LazyFrame) else lf.columns
    if area_drift is not None and area_drift.height and area_col in schema:
        # δ_area is a RATE (per year of distance from the reference month):
        # the area's constant-quality appreciation ran δ above its district's
        # curve, so a sale y years back needs δ·y MORE adjustment to reach
        # reference-month dollars.
        drift = area_drift.select(
            pl.col("market_area").alias("_drift_area"), pl.col("drift_per_yr").alias("_drift")
        )
        out = (
            out.join(drift.lazy(), left_on=area_col, right_on="_drift_area", how="left")
            .with_columns(
                (
                    pl.col(out_col)
                    + pl.col("_drift").fill_null(0.0)
                    * ((pl.lit(hi) - pl.col("_adj_month")).dt.total_days() / 365.25)
                ).alias(out_col)
            )
            .drop("_drift")
        )
    out = out.drop("_adj_month", "_adj_district", "_d_index", "_city_index")
    return out.collect() if isinstance(lf, pl.DataFrame) else out
