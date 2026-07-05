"""How much tax did OPA's regressive assessments shift, per year, in dollars.

Revenue-neutral: the levy is a target the city hits with the millage, so this is
REDISTRIBUTION, not lost revenue — the bottom tiers' overpayment equals the top
tiers' underpayment, dollar for dollar. For each year we compare OPA's roll to a
uniform-ratio "fair" roll under two model-free benchmarks for market value: raw
sale price (cash-inflated on the low end) and financed sales only (the
defensible, IAAO-style sample). The choice swings the number roughly 2x.

Method: a sold-home ratio study extrapolated to the residential roll. The
bottom-40%'s net over-assessment (as a share of the sold-sample levy) times the
year's full residential assessed base times the flat 1.3998% millage
(2016-2027 total; only the city/school split shifted, in 2025 — Philadelphia
tax-rate schedule). Tax is on GROSS assessed value: the homestead exemption
(which grew $30k -> $100k over 2012-2024 and is mildly progressive) would modestly
compress the bottom's overpayment; it is noted, not modelled. Per capita divides
the citywide figure by ~1.58M residents.

Coverage: 2016-2025 are full years; 2026 is partial (sales still accruing);
2027's roll cannot be scored — no sales have transacted under it. Uses actual
sales as market truth; the as-of-year model counterfactual is a separate study.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from philly_assessments import config
from philly_assessments.models.baseline import RESIDENTIAL_CATEGORIES
from philly_assessments.scalars import as_float

logger = logging.getLogger(__name__)

MILLAGE = 0.013998  # flat total real-estate tax rate, 2016-2027 (phila.gov schedule)
PHILADELPHIA_POP = 1_580_000  # ~US Census, roughly flat 2016-2025
_PARTIAL_YEARS = frozenset({2026})  # sales still accruing — not a full year


def _tier_redistribution(
    opa: npt.NDArray[np.float64], value: npt.NDArray[np.float64]
) -> tuple[float, float, float]:
    """(bottom-40% net over-assessment as a fraction of the levy, q1/q5 ratio,
    median ratio) for one sold sample. Revenue-neutral: fair = R*value where R is
    the aggregate ratio, so the bottom's overpayment equals the top's shortfall."""
    n = len(opa)
    ratio = opa / value
    fair_r = float(opa.sum() / value.sum())
    delta = opa - fair_r * value
    q = np.empty(n, dtype=np.int64)
    q[value.argsort()] = (np.arange(n) * 5) // n
    meds = [float(np.median(ratio[q == i])) for i in range(5)]
    bottom_frac = float(delta[(q == 0) | (q == 1)].sum() / opa.sum())
    return bottom_frac, meds[0] / meds[4], float(np.median(ratio))


def _residential_assessed_by_year(data_dir: Path | None) -> dict[int, float]:
    """Total residential market value on OPA's roll, per year — the base the
    sold-sample redistribution share extrapolates onto."""
    root = data_dir if data_dir is not None else config.data_dir()
    residential = (
        pl.scan_parquet(root / "staged" / "opa_properties.parquet")
        .filter(pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES))
        .select("parcel_number")
    )
    base = (
        pl.scan_parquet(root / "staged" / "assessments.parquet")
        .filter(pl.col("market_value").fill_null(0) > 0)
        .join(residential, left_on="parcel_number", right_on="parcel_number", how="inner")
        .group_by("year_parsed")
        .agg(pl.col("market_value").sum().alias("assessed"))
        .collect()
    )
    return {int(r["year_parsed"]): float(r["assessed"]) for r in base.to_dicts()}


def historical_redistribution(data_dir: Path | None = None) -> pl.DataFrame:
    """Per year x benchmark: regressivity, the bottom-40%'s overpayment as a
    share of the levy, and that share converted to citywide tax dollars and
    dollars per resident."""
    root = data_dir if data_dir is not None else config.data_dir()
    sf = (
        pl.read_parquet(root / "marts" / "sale_features.parquet")
        .filter(
            pl.col("sale_price").is_between(30_000, 2_000_000)
            & (pl.col("asmt_market_value_sale_year").fill_null(0) > 0)
            & ~pl.col("parcel_id").str.starts_with("88")
        )
        .with_columns(
            pl.col("sale_date").dt.year().alias("year"),
            pl.col("asmt_market_value_sale_year").alias("opa"),
        )
    )
    base = _residential_assessed_by_year(data_dir)

    rows = []
    for year in sorted(sf["year"].unique().to_list()):
        year_df = sf.filter(pl.col("year") == year)
        levy = base.get(year, 0.0) * MILLAGE
        for benchmark, sub in (
            ("raw_sale", year_df),
            ("financed", year_df.filter(pl.col("fin_cash_sale") == 0)),
        ):
            if sub.height < 500:
                continue
            opa = sub["opa"].to_numpy().astype(np.float64)
            value = sub["sale_price"].to_numpy().astype(np.float64)
            bottom_frac, q1q5, med = _tier_redistribution(opa, value)
            citywide = bottom_frac * levy
            rows.append(
                {
                    "year": year,
                    "benchmark": benchmark,
                    "partial_year": year in _PARTIAL_YEARS,
                    "n_sales": sub.height,
                    "median_ratio": round(med, 3),
                    "q1_q5_ratio": round(q1q5, 3),
                    "bottom40_overpaid_pct_levy": round(bottom_frac * 100, 2),
                    "citywide_tax_shifted_usd": round(citywide, 0),
                    "per_resident_usd": round(citywide / PHILADELPHIA_POP, 2),
                }
            )
    return pl.DataFrame(rows).sort("benchmark", "year")


# Tract majority-race groups are ecological (neighborhood, not individual) and
# diagnostic-only — never a valuation input. This overlay exists to test, not to
# assert, the "regressive assessments cost group X" claim.
_RACE_GROUPS = ("White alone", "Black alone", "Hispanic/Latino, any race")


def redistribution_by_race(data_dir: Path | None = None) -> pl.DataFrame:
    """Net over/under-payment by tract majority race, per year, on the financed
    (defensible) sample — as a share of the levy. Read the honesty note in the
    module docstring: on this sample the sign does NOT support "group X overpaid";
    it is cash-composition-mediated and time-varying."""
    from philly_assessments.diagnostics.acs_sensitivity import _acs_frame, join_tracts

    root = data_dir if data_dir is not None else config.data_dir()
    sf = (
        pl.read_parquet(root / "marts" / "sale_features.parquet")
        .filter(
            pl.col("sale_price").is_between(30_000, 2_000_000)
            & (pl.col("asmt_market_value_sale_year").fill_null(0) > 0)
            & ~pl.col("parcel_id").str.starts_with("88")
            & (pl.col("fin_cash_sale") == 0)
        )
        .with_columns(
            pl.col("sale_date").dt.year().alias("year"),
            pl.col("asmt_market_value_sale_year").alias("opa"),
        )
    )
    acs = _acs_frame(data_dir)

    rows = []
    for year in sorted(sf["year"].unique().to_list()):
        d = join_tracts(sf.filter(pl.col("year") == year), acs)
        if d.height < 500:
            continue
        fair_r = as_float(d["opa"].sum()) / as_float(d["sale_price"].sum())
        d = d.with_columns((pl.col("opa") - fair_r * pl.col("sale_price")).alias("delta"))
        levy = as_float(d["opa"].sum())
        for group in _RACE_GROUPS:
            sub = d.filter(pl.col("acs_majority_race") == group)
            if sub.height < 200:
                continue
            rows.append(
                {
                    "year": year,
                    "tract_majority_race": group,
                    "n_sales": sub.height,
                    "net_overpaid_pct_levy": round(as_float(sub["delta"].sum()) / levy * 100, 2),
                }
            )
    return pl.DataFrame(rows).sort("tract_majority_race", "year")
