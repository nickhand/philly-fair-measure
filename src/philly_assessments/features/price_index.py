"""District monthly price index — OPA-style compound time adjustment.

OPA calibrates every sale to the valuation date with a compound monthly index
and then drops time from its models; our v1 models carried time features and
visibly mis-extrapolated (docs/feature-plan-v2.md §1.1). This module builds a
monthly log-$/sqft index per learned district (market_areas.py), shrunk toward
the citywide index where monthly sale counts are thin:

    index_dm = (n_dm * median_dm + LAMBDA * median_cm) / (n_dm + LAMBDA)

then 3-month centered smoothing, normalized so the latest month is 0. The
special district ``__city__`` carries the citywide index and is the fallback
for parcels without a district.

`with_time_adjustment` attaches ``time_adj_log`` = -log_index(month(date)):
adding it to log(price) expresses the sale in reference-month dollars; models
trained on adjusted prices predict at reference level, and predictions are
moved back to any date by subtracting the adjustment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import overload

import polars as pl

from philly_assessments import config
from philly_assessments.features.market_areas import sale_points
from philly_assessments.ingest.derived import write_derived_table
from philly_assessments.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest

logger = logging.getLogger(__name__)

SHRINKAGE_LAMBDA = 15.0
SMOOTH_MONTHS = 3
CITYWIDE = "__city__"


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest


def build_price_index(data_dir: Path | None = None) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    paths = {
        "opa": root / "staged" / "opa_properties.parquet",
        "sales": root / "marts" / "sale_validity.parquet",
        "market_areas": root / "marts" / "market_areas.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `philly build-market-areas` first")

    points = sale_points(pl.scan_parquet(paths["sales"]), pl.scan_parquet(paths["opa"]))
    districts = pl.read_parquet(paths["market_areas"]).select("parcel_id", "district")
    points = points.join(districts, on="parcel_id", how="left").with_columns(
        pl.col("district").fill_null(CITYWIDE)
    )

    citywide = points.group_by("month").agg(
        pl.col("log_ppsf").median().alias("city_med"), pl.len().alias("city_n")
    )
    by_district = points.group_by("district", "month").agg(
        pl.col("log_ppsf").median().alias("district_med"), pl.len().alias("n_sales")
    )

    # complete (district x month) grid so every month has an index value;
    # CITYWIDE is appended separately below, so keep it out of the grid
    months = citywide.select("month").sort("month")
    district_names = [
        d for d in points["district"].unique().to_list() if d != CITYWIDE
    ]
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
        notes=f"lambda={SHRINKAGE_LAMBDA} smooth={SMOOTH_MONTHS}mo; "
        f"log_index normalized to 0 at the latest month; {CITYWIDE} = fallback",
    )
    return BuildResult(path=path, manifest=manifest)


@overload
def with_time_adjustment(
    lf: pl.DataFrame,
    index: pl.DataFrame,
    *,
    district_col: str = ...,
    date_col: str = ...,
    out_col: str = ...,
) -> pl.DataFrame: ...


@overload
def with_time_adjustment(
    lf: pl.LazyFrame,
    index: pl.DataFrame,
    *,
    district_col: str = ...,
    date_col: str = ...,
    out_col: str = ...,
) -> pl.LazyFrame: ...


def with_time_adjustment(
    lf: pl.LazyFrame | pl.DataFrame,
    index: pl.DataFrame,
    *,
    district_col: str = "loc_district",
    date_col: str = "sale_date",
    out_col: str = "time_adj_log",
) -> pl.LazyFrame | pl.DataFrame:
    """Attach ``out_col`` = -log_index(district, month(date)), clamped to the
    index's month range; falls back to the citywide index for unknown districts.
    A DataFrame in gives a DataFrame back; a LazyFrame stays lazy."""
    bounds = index.select(pl.col("month").min().alias("lo"), pl.col("month").max().alias("hi"))
    lo, hi = bounds.row(0)
    city = index.filter(pl.col("district") == CITYWIDE).select(
        "month", pl.col("log_index").alias("_city_index")
    )
    district_index = index.select("district", "month", pl.col("log_index").alias("_d_index"))

    out = (
        lf.lazy()
        .with_columns(
            pl.col(date_col)
            .dt.truncate("1mo")
            .clip(pl.lit(lo), pl.lit(hi))
            .alias("_adj_month"),
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
        .with_columns(
            (-pl.coalesce("_d_index", "_city_index").fill_null(0.0)).alias(out_col)
        )
        .drop("_adj_month", "_adj_district", "_d_index", "_city_index")
    )
    return out.collect() if isinstance(lf, pl.DataFrame) else out
