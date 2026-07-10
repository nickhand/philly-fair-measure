"""Is the vertical inequity real, or a binning artifact?

The classic regressivity chart bins each sale by its own price, so an
individually mis-priced transaction (a foreclosure or family transfer that
slipped validation) lands in the bottom bin by construction and inflates its
ratio — Doucet's "over-assessing low-priced homes vs. over-assessing poor
people's homes" critique. The artifact-robust version re-bins each sale by the
price level of its *neighborhood*: the mis-validated bargain in a rich
neighborhood moves to the top bin where it belongs, while a systematically
over-assessed poor neighborhood stays at the bottom.

Neighborhood = the learned market areas (the sale-derived price communities
behind the price index), with census tracts as a sensitivity. A neighborhood's
level is the median reference-frame price over the full arms-length pool, so
each level rests on hundreds of sales, and areas with fewer than `min_sales`
are excluded from the binning (and counted) rather than contributing noise.

The map-test companion: kNN Moran's I of log assessment ratios. Genuine bias
clusters spatially; validation leakage sprinkles randomly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.scoring import latest_run_dir

logger = logging.getLogger(__name__)

MIN_AREA_SALES = 50
MORANS_K = 10


def q1q5_medians(by: np.ndarray, ratio: np.ndarray) -> tuple[float, float, int, int]:
    """Median ratio in the bottom/top quintile of `by` (edges over sales)."""
    ok = np.isfinite(by) & np.isfinite(ratio)
    by, ratio = by[ok], ratio[ok]
    lo, hi = np.quantile(by, [0.2, 0.8])
    q1, q5 = by <= lo, by >= hi
    return (
        float(np.median(ratio[q1])),
        float(np.median(ratio[q5])),
        int(q1.sum()),
        int(q5.sum()),
    )


def neighborhood_levels(
    sf: pl.DataFrame, *, area_col: str = "loc_market_area", min_sales: int = MIN_AREA_SALES
) -> pl.DataFrame:
    """(area, level, n) — median reference-frame price per neighborhood.

    Levels come from the full arms-length pool (every sale time-adjusted to the
    index reference month, so an area that mostly transacted years ago does not
    read as cheap merely for being old). Areas under `min_sales` are dropped:
    a median over a handful of sales is noise, not a price level.
    """
    return (
        sf.drop_nulls(area_col)
        .with_columns(
            (pl.col("sale_price") * pl.col("time_adj_log").fill_null(0.0).exp()).alias("price_ref")
        )
        .group_by(area_col)
        .agg(pl.col("price_ref").median().alias("nbhd_level"), pl.len().alias("nbhd_n"))
        .filter(pl.col("nbhd_n") >= min_sales)
    )


def morans_i(lon: np.ndarray, lat: np.ndarray, z: np.ndarray, *, k: int = MORANS_K) -> float:
    """kNN Moran's I of `z` — 0 means spatially random, higher means clustered."""
    from scipy.spatial import cKDTree

    ok = np.isfinite(lon) & np.isfinite(lat) & np.isfinite(z)
    lon, lat, z = lon[ok], lat[ok], z[ok]
    n = len(z)
    if n < 3:
        return 0.0
    zc = z - z.mean()
    var = float(zc.var())
    if var == 0.0:
        return 0.0
    xy = np.column_stack([lon * np.cos(np.deg2rad(float(lat.mean()))), lat])
    # drop each row's own index explicitly rather than assuming it arrives
    # first: with exact duplicate coordinates (condo stacks, shared parcels)
    # a tie can precede self, and leaving z_i inside its own lag biases I up
    _, ix = cKDTree(xy).query(xy, k=min(k + 1, n))
    lag = np.zeros(n)
    for i in range(n):
        neighbors = ix[i][ix[i] != i][:k]
        if len(neighbors):
            lag[i] = zc[neighbors].mean()
    return float((zc * lag).mean() / var)


def _ratio(value: np.ndarray, price: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.where((price > 0) & np.isfinite(value) & (value > 0), value / price, np.nan)


def equity_robustness(
    data_dir: Path | None = None, *, min_sales: int = MIN_AREA_SALES
) -> dict[str, Any]:
    """The 2x2 (all/financed x individual/neighborhood binning) for OPA and the
    model on the out-of-time test set, plus the Moran's-I map test and a tract
    sensitivity. Returns plain floats/ints, JSON-ready."""
    root = data_dir if data_dir is not None else config.data_dir()
    sf = pl.read_parquet(
        root / "marts" / "sale_features.parquet",
        columns=[
            "sale_id",
            "sale_price",
            "time_adj_log",
            "fin_cash_sale",
            "loc_market_area",
            "loc_census_tract_raw",
            "loc_lon",
            "loc_lat",
        ],
    )
    areas = neighborhood_levels(sf, min_sales=min_sales)
    tracts = neighborhood_levels(sf, area_col="loc_census_tract_raw", min_sales=min_sales).rename(
        {"nbhd_level": "tract_level", "nbhd_n": "tract_n"}
    )

    run_dir = latest_run_dir("baseline", root)
    preds = (
        pl.read_parquet(run_dir / "predictions.parquet")
        .join(
            sf.select(
                "sale_id",
                "fin_cash_sale",
                "loc_market_area",
                "loc_census_tract_raw",
                "loc_lon",
                "loc_lat",
            ),
            on="sale_id",
            how="left",
        )
        .join(areas, on="loc_market_area", how="left")
        .join(tracts, on="loc_census_tract_raw", how="left")
    )

    def cells(frame: pl.DataFrame, by_col: str) -> dict[str, Any]:
        price = frame["sale_price"].to_numpy().astype(np.float64)
        by = frame[by_col].to_numpy().astype(np.float64)
        out: dict[str, Any] = {}
        for name, col in (("opa", "opa_assessment"), ("model", "pred_lightgbm")):
            r = _ratio(frame[col].to_numpy().astype(np.float64), price)
            q1, q5, n1, n5 = q1q5_medians(by, r)
            out[name] = {"q1": round(q1, 3), "q5": round(q5, 3), "n_q1": n1, "n_q5": n5}
        return out

    financed = preds.filter(pl.col("fin_cash_sale").fill_null(1.0) == 0.0)
    result: dict[str, Any] = {
        "all_sales": {
            "individual": cells(preds, "sale_price"),
            "neighborhood": cells(preds, "nbhd_level"),
        },
        "financed": {
            "individual": cells(financed, "sale_price"),
            "neighborhood": cells(financed, "nbhd_level"),
        },
        "tract_sensitivity": cells(preds, "tract_level"),
        "meta": {
            "n_areas": areas.height,
            "median_area_sales": int(np.median(areas["nbhd_n"].to_numpy())) if areas.height else 0,
            "min_area_sales": min_sales,
            "test_rows": preds.height,
            "test_rows_without_area": int(preds["nbhd_level"].null_count()),
        },
    }

    p = financed["sale_price"].to_numpy().astype(np.float64)
    lon = financed["loc_lon"].to_numpy().astype(np.float64)
    lat = financed["loc_lat"].to_numpy().astype(np.float64)
    for name, col in (("opa", "opa_assessment"), ("model", "pred_lightgbm")):
        r = _ratio(financed[col].to_numpy().astype(np.float64), p)
        with np.errstate(all="ignore"):
            result["meta"][f"morans_i_{name}"] = round(morans_i(lon, lat, np.log(r)), 3)
    logger.info(
        "equity robustness: OPA nbhd-binned q1 %.3f / q5 %.3f (individual %.3f / %.3f)",
        result["all_sales"]["neighborhood"]["opa"]["q1"],
        result["all_sales"]["neighborhood"]["opa"]["q5"],
        result["all_sales"]["individual"]["opa"]["q1"],
        result["all_sales"]["individual"]["opa"]["q5"],
    )
    return result
