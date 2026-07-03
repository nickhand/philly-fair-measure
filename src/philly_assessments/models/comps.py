"""Comparable sales via shared LightGBM leaf assignments (the CCAO design).

A property's comps are the validated arms-length sales that repeatedly land in
the same leaves of the trained valuation model's trees. Two properties share a
leaf only when every split on the path — location, size, style, condition,
market context — sorts them together, so shared-leaf frequency is similarity
*as the model prices it*, not an ad-hoc filter cascade. This is the
interpretable appeal-evidence output the project brief calls for: each comp is
a real, recent, arms-length sale, shown with its price both as transacted and
adjusted to today via the district price index.

Requires marts/assessment_features.parquet (persisted by
`philly screen-assessments`) for the target property's current features, and a
persisted baseline run for the model.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import config
from philly_assessments.models.scoring import latest_run_dir, run_params

logger = logging.getLogger(__name__)

DEFAULT_K = 10
DEFAULT_WINDOW_YEARS = 5.0


@dataclass(frozen=True)
class CompsResult:
    target: dict
    comps: pl.DataFrame


def _leaf_matrix(run_dir: Path, df: pl.DataFrame) -> np.ndarray:
    import json

    import lightgbm as lgb

    from philly_assessments.models.baseline import _encode

    booster = lgb.Booster(model_file=str(run_dir / "model_lightgbm.txt"))
    mappings = json.loads((run_dir / "categorical_mappings.json").read_text())
    params = run_params(run_dir)
    x = _encode(df, mappings, params["numeric_features"], params["categorical_features"])
    return booster.predict(x, pred_leaf=True).astype(np.int32)


def _distance_m(lon0, lat0, lon: pl.Expr, lat: pl.Expr) -> pl.Expr:
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0 or 39.95))
    return (
        ((lon - lon0) * m_per_deg_lon) ** 2 + ((lat - lat0) * 110_540.0) ** 2
    ).sqrt().alias("distance_m")


def find_comps(
    parcel_id: str,
    data_dir: Path | None = None,
    *,
    k: int = DEFAULT_K,
    window_years: float = DEFAULT_WINDOW_YEARS,
) -> CompsResult:
    root = data_dir if data_dir is not None else config.data_dir()
    features_path = root / "marts" / "assessment_features.parquet"
    sales_path = root / "marts" / "sale_features.parquet"
    if not features_path.exists():
        raise FileNotFoundError(
            f"{features_path} missing; run `philly screen-assessments` first"
        )

    target_df = pl.read_parquet(features_path).filter(pl.col("parcel_id") == parcel_id)
    if target_df.height == 0:
        raise KeyError(f"parcel {parcel_id!r} not found in assessment features")
    target_df = target_df.head(1)

    pool = pl.read_parquet(sales_path)
    anchor = pool["sale_date"].max()
    pool = pool.filter(
        (pl.col("sale_date") >= anchor - pl.duration(days=int(window_years * 365.25)))
        & (pl.col("parcel_id") != parcel_id)
    )
    logger.info("comps pool: %s sales in the last %.1fy", f"{pool.height:,}", window_years)

    run_dir = latest_run_dir("baseline", data_dir)
    target_leaves = _leaf_matrix(run_dir, target_df)  # (1, n_trees)
    pool_leaves = _leaf_matrix(run_dir, pool)  # (n, n_trees)
    similarity = (pool_leaves == target_leaves).mean(axis=1)

    top = np.argsort(-similarity)[:k]
    lon0 = target_df["loc_lon"][0]
    lat0 = target_df["loc_lat"][0]
    comps = (
        pool[top.tolist()]
        .with_columns(
            pl.Series("similarity", similarity[top]),
            (pl.col("sale_price") * pl.col("time_adj_log").exp()).alias("price_adj_today"),
            _distance_m(lon0, lat0, pl.col("loc_lon"), pl.col("loc_lat")),
        )
        .select(
            "parcel_id",
            "sale_id",
            "sale_date",
            "sale_price",
            "price_adj_today",
            "similarity",
            "distance_m",
            "char_livable_area",
            "char_style",
            "char_era",
            "char_interior_condition",
            "loc_zip5",
        )
        .sort("similarity", descending=True)
    )
    # attach addresses from the staged roll (sale features carry ids only)
    addresses = (
        pl.scan_parquet(root / "staged" / "opa_properties.parquet")
        .select(pl.col("parcel_number").alias("parcel_id"), pl.col("location").alias("address"))
        .collect()
    )
    comps = comps.join(addresses, on="parcel_id", how="left")

    target = target_df.to_dicts()[0]
    return CompsResult(target=target, comps=comps)


def resolve_parcel(query: str, data_dir: Path | None = None) -> list[dict]:
    """Resolve a parcel id or address fragment to candidate parcels (max 5)."""
    root = data_dir if data_dir is not None else config.data_dir()
    features = pl.scan_parquet(root / "marts" / "assessment_features.parquet")
    if query.isdigit():
        matches = features.filter(pl.col("parcel_id") == query)
    else:
        matches = features.filter(
            pl.col("address")
            .cast(pl.String)
            .str.to_uppercase()
            .str.contains(query.upper(), literal=True)
        )
    return (
        matches.select("parcel_id", "address", "opa_market_value")
        .head(5)
        .collect()
        .to_dicts()
    )
