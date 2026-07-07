"""Constant-quality price index: a three-level BMN repeat-sales hierarchy.

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

v2 (this module) is constant-quality by construction — a three-level BMN
repeat-sales hierarchy, each level ridge-shrunk toward its parent:

- **BMN repeat-sales regression** (Bailey–Muth–Nourse): quarterly dummies fit
  to Δlog(price) of same-parcel arms-length pairs, then interpolated to
  months, smoothed, normalized so the trailing-year mean level is 0. Pair
  hygiene: held ≥ ~6 months, |annualized Δlog| ≤ 0.35 (drops flips/gut
  renovations — those pairs are quality CHANGES, not appreciation).
- **Three geographies** in one table, keyed by the ``district`` column (the
  namespaces ``__city__`` / ``d_NN`` / ``ma_NNN`` never collide): a citywide
  curve (no prior), per-district curves shrunk toward citywide, and — for
  market areas with ≥ ``MIN_PAIRS_FOR_AREA`` pairs — per-market-area curves
  shrunk toward their district. The area level replaced a constant per-area
  *drift* rate (v2.0): the drift couldn't express a sub-area that tracked its
  district then diverged, so ma_146 (2314 Wallace St), which outran d_10 pre-
  2010 and lagged it −0.17 after 2022, averaged to a ~0 drift and inherited
  the district's full climb. A quarterly curve carries the sign flip.

Fixtures with too few repeat pairs fall back to the v1 median-ppsf
construction automatically (district/citywide only, no area curves).

`with_time_adjustment` attaches ``time_adj_log`` = −log_index(geo, month) for
the most specific geography available (market area → district → citywide):
adding it to log(price) expresses the sale in reference-month dollars; models
trained on adjusted prices predict at reference level, and predictions are
moved back to any date by subtracting the adjustment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
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
SMOOTH_MONTHS = 5
# The reference ("today, index 0") is the trailing-year average level, not the
# single latest month: at the market-area level the most recent month is thin
# (ma_146 ~1 pair/month) and its noise anchored the WHOLE area index, hiding
# the real divergence — a 12-month average is a stable "current level" that
# recovers ma_146's measured −0.17 lag vs its district (the 2314 Wallace fix).
REFERENCE_TRAILING_MONTHS = 12
CITYWIDE = "__city__"

# repeat-sales machinery (v2 constant-quality index)
MIN_PAIRS_FOR_BMN = 500  # below this (unit fixtures), fall back to median-ppsf
MIN_PAIRS_FOR_AREA = 200  # market areas thinner than this inherit the district curve
PAIR_MIN_HELD_YEARS = 0.49
PAIR_MAX_ANNUAL_LOG = 0.35  # flips/gut renos are quality changes, not appreciation
PAIR_FLOOR_PRICE = 10_000.0
BMN_START = "1997-01-01"  # RTT records begin; earlier dates are parse garbage
RIDGE_TAU = 25.0  # districts pull firmly toward the citywide curve
# Market areas pull only gently toward their district: at RIDGE_TAU the
# district's climb swamped a real sub-area divergence (ma_146's systematic
# −0.11..−0.29 recent underperformance vs d_10 shrank to ~0). Measured on
# ma_146's 842 pairs, τ=6 keeps ~70% of the unshrunk divergence while the
# 200-pair floor keeps thin areas from chasing quarter-level noise.
AREA_RIDGE_TAU = 6.0


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


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
    q1: np.ndarray,
    q2: np.ndarray,
    dlog: np.ndarray,
    n_quarters: int,
    prior: np.ndarray | None,
    *,
    ridge_tau: float = RIDGE_TAU,
) -> np.ndarray:
    """Quarterly log-level curve from pair data: least squares on ±1 quarter
    dummies (quarter 0 pinned to 0), optionally ridge-pulled toward a prior
    curve (its parent geography) so thin cells stay sane. ``ridge_tau`` sets
    how hard: districts pull firmly toward citywide (RIDGE_TAU), market areas
    pull gently toward their district (AREA_RIDGE_TAU) so a well-supported
    area's real divergence survives."""
    rows = np.arange(len(dlog))
    a = np.zeros((len(dlog), n_quarters - 1))
    for q, sign in ((q2, 1.0), (q1, -1.0)):
        mask = q > 0
        a[rows[mask], q[mask] - 1] += sign
    y = dlog.copy()
    if prior is not None:
        tau = np.sqrt(ridge_tau)
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


def _snap_area_tail_to_district(
    index: pl.DataFrame, area_to_district: dict[str, str], cutoff: datetime
) -> pl.DataFrame:
    """For months ``>= cutoff``, replace each market area's log_index with its
    district's.

    Area curves are thin at the recent endpoint (~1-8 pairs/month), and their
    monthly values there are noise, not signal (ma_146 swung -0.21 -> +0.18 in
    nine months while its $/sqft stayed flat). The trailing-mean reference fixes
    the anchor, but the valuation-date move reads the endpoint month directly,
    so that noise moved every area home's shown estimate by up to ~20%. Snapping
    the tail to the district keeps each area's HISTORICAL divergence (older
    months, where it has pair evidence) and tracks the district recently, where
    it does not. District and citywide rows are untouched (they have no parent)."""
    parents = pl.DataFrame(
        {"district": list(area_to_district), "_parent": list(area_to_district.values())}
    )
    parent_li = index.select(
        pl.col("district").alias("_parent"), "month", pl.col("log_index").alias("_parent_li")
    )
    return (
        index.join(parents, on="district", how="left")
        .join(parent_li, on=["_parent", "month"], how="left")
        .with_columns(
            pl.when(pl.col("_parent").is_not_null() & (pl.col("month") >= cutoff))
            .then(pl.col("_parent_li"))
            .otherwise(pl.col("log_index"))
            .alias("log_index")
        )
        .drop("_parent", "_parent_li")
        .sort("district", "month")
    )


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
        pl.col("level").sort_by("month").tail(REFERENCE_TRAILING_MONTHS).mean().alias("ref_level"),
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
        f"log_index 0 at the trailing-year mean; {CITYWIDE} = fallback",
    )
    return BuildResult(path=path, manifest=manifest)


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

    # level 1: citywide (no prior). level 2: districts shrunk toward citywide.
    city_curve = _bmn_curve(q1, q2, dlog, n_quarters, prior=None)
    district_names = [d for d in points["district"].unique().to_list() if d != CITYWIDE]
    curves: dict[str, np.ndarray] = {CITYWIDE: city_curve}
    for name in district_names:
        mask = district_arr == name
        if int(mask.sum()) == 0:
            curves[name] = city_curve
            continue
        curves[name] = _bmn_curve(q1[mask], q2[mask], dlog[mask], n_quarters, prior=city_curve)
        logger.info("BMN district %s: %d pairs", name, int(mask.sum()))

    # level 3: market-area curves for well-supported areas, shrunk toward their
    # OWN district curve. This is what a constant per-area drift could not do —
    # express an area that tracked its district then diverged (ma_146 outran
    # d_10 pre-2010, lagged it recently; the two-sided residual averaged to 0).
    area_arr = pairs["market_area"].to_numpy()
    area_to_district = dict(
        pairs.select("market_area", "district").drop_nulls("market_area").unique().iter_rows()
    )
    area_counts = pairs.drop_nulls("market_area").group_by("market_area").len().sort("market_area")
    eligible = area_counts.filter(pl.col("len") >= MIN_PAIRS_FOR_AREA)["market_area"].to_list()
    for area in eligible:
        mask = area_arr == area
        prior = curves.get(area_to_district.get(area, CITYWIDE), city_curve)
        curves[area] = _bmn_curve(
            q1[mask], q2[mask], dlog[mask], n_quarters, prior=prior, ridge_tau=AREA_RIDGE_TAU
        )
    logger.info("BMN market-area curves: %d of %d areas", len(eligible), area_counts.height)

    # quarterly curves -> the monthly index table. n_sales is per-geo metadata:
    # count sales under each district key AND each area key (same namespaces the
    # curves use), so every emitted row carries its own support.
    pts_geo = points.join(
        pl.read_parquet(paths["market_areas"]).select("parcel_id", "market_area"),
        on="parcel_id",
        how="left",
    )
    n_sales = pl.concat(
        [
            pts_geo.drop_nulls(key)
            .group_by(pl.col(key).alias("geo"), "month")
            .agg(pl.len().alias("n_sales"))
            for key in ("district", "market_area")
        ]
    ).rename({"geo": "district"})
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
        pl.col("level").sort_by("month").tail(REFERENCE_TRAILING_MONTHS).mean().alias("ref_level"),
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

    if eligible:
        month_list = months.sort()
        cutoff = month_list[max(0, month_list.len() - REFERENCE_TRAILING_MONTHS)]
        index = _snap_area_tail_to_district(index, area_to_district, cutoff)

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
        notes=f"BMN repeat-sales (city/district/market-area), {pairs.height} pairs, "
        f"tau={RIDGE_TAU}, area threshold={MIN_PAIRS_FOR_AREA} pairs, smooth={SMOOTH_MONTHS}mo; "
        f"log_index 0 at the trailing-year mean; {CITYWIDE} = fallback",
    )
    logger.info(
        "repeat-sales index: %d pairs, %d districts, %d market-area curves",
        pairs.height,
        len(district_names),
        len(eligible),
    )
    return BuildResult(path=path, manifest=manifest)


@overload
def with_time_adjustment(
    lf: pl.DataFrame,
    index: pl.DataFrame,
    *,
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
    district_col: str = ...,
    area_col: str = ...,
    date_col: str = ...,
    out_col: str = ...,
) -> pl.LazyFrame: ...


def with_time_adjustment(
    lf: pl.LazyFrame | pl.DataFrame,
    index: pl.DataFrame,
    *,
    district_col: str = "loc_district",
    area_col: str = "loc_market_area",
    date_col: str = "sale_date",
    out_col: str = "time_adj_log",
) -> pl.LazyFrame | pl.DataFrame:
    """Attach ``out_col`` = −log_index(geo, month(date)) for the most specific
    geography the row carries — market area, then district, then citywide —
    clamped to the index's month range. The index keys all three in one
    ``district`` column (``ma_NNN`` / ``d_NN`` / ``__city__`` never collide),
    so unknown areas fall through to the district curve and unknown districts
    to citywide. A DataFrame in gives a DataFrame back; a LazyFrame stays
    lazy."""
    bounds = index.select(pl.col("month").min().alias("lo"), pl.col("month").max().alias("hi"))
    lo, hi = bounds.row(0)
    city = index.filter(pl.col("district") == CITYWIDE).select(
        "month", pl.col("log_index").alias("_city_index")
    )
    district_index = index.select("district", "month", pl.col("log_index").alias("_d_index"))
    area_index = index.select(
        pl.col("district").alias("_area_key"), "month", pl.col("log_index").alias("_area_index")
    )

    schema = lf.collect_schema().names() if isinstance(lf, pl.LazyFrame) else lf.columns
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
        .join(city.lazy(), left_on="_adj_month", right_on="month", how="left")
    )
    sources = ["_d_index", "_city_index"]
    drop = ["_adj_month", "_adj_district", "_d_index", "_city_index"]
    if area_col in schema:
        # only ``ma_NNN`` values ever match a loc_market_area, so the whole
        # index can be offered — district/city keys simply never join here.
        out = out.join(
            area_index.lazy(),
            left_on=[area_col, "_adj_month"],
            right_on=["_area_key", "month"],
            how="left",
        )
        sources = ["_area_index", *sources]
        drop = ["_area_index", *drop]
    out = out.with_columns((-pl.coalesce(*sources).fill_null(0.0)).alias(out_col)).drop(drop)
    return out.collect() if isinstance(lf, pl.DataFrame) else out
