"""Annual assessment-roll change and provisional equity diagnostics.

This is deliberately *not* a sales-ratio study.  A newly published roll has no
sales under its effective tax year yet, so the defensible release-day question
is narrower: did each assessment move toward or away from an independent,
current-date model estimate?  The public report labels that comparison
provisional and replaces it with post-effective-date sale evidence as it
accrues.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from sklearn.neighbors import NearestNeighbors

from philly_fair_measure.models.metrics import ratio_metrics, vertical_equity_indicator


@dataclass(frozen=True)
class AnnualRollConfig:
    """Parameters whose meaning must stay visible in every annual report."""

    tax_year: int
    comparison_year: int
    effective_date: str
    sales_cutoff: str
    millage: float = 0.013998
    min_log_direction: float = 0.02
    min_area_n: int = 500


@dataclass(frozen=True)
class BoundaryTransectConfig:
    """A reproducible proxy for examining both sides of a market boundary."""

    id: str
    core_label: str
    corridor_label: str
    boundary_label: str
    core_zips: tuple[str, ...]
    corridor_zips: tuple[str, ...]
    distance_breaks_m: tuple[int, ...] = (500, 1_000, 1_500, 2_500)


KENSINGTON_BOUNDARY_TRANSECT = BoundaryTransectConfig(
    id="kensington-fishtown",
    core_label="19122 + 19125 side",
    corridor_label="Kensington-side ZIPs",
    boundary_label="19122 / 19125 core-edge proxy",
    core_zips=("19122", "19125"),
    corridor_zips=("19133", "19134", "19140", "19124"),
)

EARTH_RADIUS_M = 6_371_008.8

RACE_CONTEXT_LABELS = {
    "White alone": "Majority-White tracts",
    "Black alone": "Majority-Black tracts",
    "Hispanic/Latino, any race": "Majority-Hispanic tracts",
}


def _pct(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else round(float(numerator) / float(denominator) * 100, 1)


def _required(frame: pl.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing required columns: {sorted(missing)}")


def _roll_metrics(assessment: np.ndarray, benchmark: np.ndarray) -> dict[str, float | None]:
    """Return model-benchmark ratio measures for one assessment roll.

    These are provisional diagnostics, not a sales-ratio study: the same
    independent estimate is the market-value proxy for both rolls.  Keeping
    the calculation here ensures the public headline and the displayed
    figures are generated from the same matched records.
    """

    ratio = ratio_metrics(assessment, benchmark)
    vei = vertical_equity_indicator(assessment, benchmark)

    def rounded(value: float | None, digits: int) -> float | None:
        return None if value is None else round(value, digits)

    return {
        "cod": rounded(ratio.cod, 1),
        "prd": rounded(ratio.prd, 4),
        "prb": rounded(ratio.prb, 4),
        "vei": rounded(vei.vei, 1),
    }


def _direction_expr(min_log_direction: float) -> pl.Expr:
    """Classify a meaningful change in absolute log error to the model point.

    A two-log-point deadband (the default) prevents a token movement or normal
    rounding from becoming a fairness claim.  Records with a known source-data
    warning are assessed but kept out of the direction verdict.
    """

    return (
        pl.when(pl.col("_data_warning"))
        .then(pl.lit("data_warning"))
        .when(pl.col("_new_error") < pl.col("_old_error") - min_log_direction)
        .then(pl.lit("corrective"))
        .when(pl.col("_new_error") > pl.col("_old_error") + min_log_direction)
        .then(pl.lit("widening"))
        .otherwise(pl.lit("no_clear_change"))
        .alias("_direction")
    )


def _distance_label(lower_m: int, upper_m: int | None) -> str:
    def km(value: int) -> str:
        result = value / 1_000
        return str(int(result)) if result.is_integer() else str(result)

    if upper_m is None:
        return f"{km(lower_m)}+ km"
    return f"{km(lower_m)}–{km(upper_m)} km"


def _transect_summary(frame: pl.DataFrame, label: str) -> dict[str, Any]:
    row = frame.select(
        pl.len().alias("n"),
        pl.col("_change").median().alias("median_change"),
        pl.col("_old_ratio").median().alias("old_ratio"),
        pl.col("_new_ratio").median().alias("new_ratio"),
        (pl.col("_direction") == "corrective").sum().alias("n_corrective"),
        (pl.col("_direction") == "widening").sum().alias("n_widening"),
        (pl.col("_direction") == "no_clear_change").sum().alias("n_no_clear"),
        pl.col("display_median").median().alias("benchmark_median"),
    ).to_dicts()[0]
    n = int(row["n"])
    return {
        "label": label,
        "n": n,
        "median_change_pct": round(float(row["median_change"]) * 100, 1),
        "old_ratio_pct": round(float(row["old_ratio"]) * 100, 1),
        "new_ratio_pct": round(float(row["new_ratio"]) * 100, 1),
        "corrective_pct": _pct(int(row["n_corrective"]), n),
        "widening_pct": _pct(int(row["n_widening"]), n),
        "no_clear_pct": _pct(int(row["n_no_clear"]), n),
        "benchmark_median_usd": round(float(row["benchmark_median"])),
    }


def build_boundary_transect(
    matched: pl.DataFrame,
    locations: pl.DataFrame,
    config: BoundaryTransectConfig,
) -> dict[str, Any]:
    """Measure change direction by distance from a reproducible boundary proxy.

    Distance is to the nearest scored residential parcel in the core ZIPs.  It
    is deliberately described as a proxy: ZIP edges are stable and repeatable,
    but they are not asserted to be exact neighborhood or market boundaries.
    Known record-quality warnings are excluded before fitting the boundary or
    calculating any band statistic.
    """

    _required(locations, {"parcel_id", "loc_lon", "loc_lat"}, "parcel locations")
    located = (
        matched.filter(~pl.col("_data_warning"))
        .join(
            locations.select("parcel_id", "loc_lon", "loc_lat").unique("parcel_id"),
            on="parcel_id",
            how="left",
        )
        .drop_nulls(["loc_lon", "loc_lat"])
        .filter(
            pl.col("loc_lon").is_between(-180.0, 180.0) & pl.col("loc_lat").is_between(-90.0, 90.0)
        )
    )
    core = located.filter(pl.col("loc_zip5").is_in(config.core_zips))
    corridor = located.filter(pl.col("loc_zip5").is_in(config.corridor_zips))
    if core.is_empty() or corridor.is_empty():
        raise ValueError("boundary transect needs located records on both sides")

    # BallTree haversine distance avoids treating longitude degrees as a fixed
    # distance.  Coordinates are [latitude, longitude] in radians.
    core_radians = np.deg2rad(core.select("loc_lat", "loc_lon").to_numpy())
    corridor_radians = np.deg2rad(corridor.select("loc_lat", "loc_lon").to_numpy())
    neighbors = NearestNeighbors(n_neighbors=1, algorithm="ball_tree", metric="haversine")
    neighbors.fit(core_radians)
    angular_distance, _ = neighbors.kneighbors(corridor_radians)
    corridor = corridor.with_columns(
        pl.Series("_boundary_distance_m", angular_distance[:, 0] * EARTH_RADIUS_M)
    )

    band_rows: list[dict[str, Any]] = []
    lower = 0
    bounds: tuple[int | None, ...] = (*config.distance_breaks_m, None)
    for upper in bounds:
        selected = corridor.filter(pl.col("_boundary_distance_m") >= lower)
        if upper is not None:
            selected = selected.filter(pl.col("_boundary_distance_m") < upper)
        if not selected.is_empty():
            summary = _transect_summary(selected, _distance_label(lower, upper))
            summary.update(
                {
                    "distance_min_m": lower,
                    "distance_max_m": upper,
                    "median_distance_m": round(float(selected["_boundary_distance_m"].median())),
                }
            )
            band_rows.append(summary)
        if upper is not None:
            lower = upper

    return {
        "id": config.id,
        "core_label": config.core_label,
        "corridor_label": config.corridor_label,
        "boundary_label": config.boundary_label,
        "core_zips": list(config.core_zips),
        "corridor_zips": list(config.corridor_zips),
        "distance_method": "Nearest reliable residential parcel in the core ZIPs",
        "n_core": core.height,
        "n_corridor": corridor.height,
        "core": _transect_summary(core, config.core_label),
        "bands": band_rows,
    }


def build_annual_roll_report(
    assessments: pl.DataFrame,
    screen: pl.DataFrame,
    config: AnnualRollConfig,
    locations: pl.DataFrame | None = None,
    demographics: pl.DataFrame | None = None,
    boundary_transect: BoundaryTransectConfig = KENSINGTON_BOUNDARY_TRANSECT,
) -> dict[str, Any]:
    """Build the JSON-safe data contract consumed by the annual web report.

    Scope is the residential model family with positive values in both rolls.
    Condominiums remain out until the annual condo comparison has a dedicated,
    like-for-like contract; mixing the two would make both the roll-change and
    value-tier results harder to interpret.
    """

    _required(
        assessments,
        {"parcel_number", "year_parsed", "market_value"},
        "assessments",
    )
    _required(
        screen,
        {
            "parcel_id",
            "model_family",
            "loc_zip5",
            "opa_market_value",
            "display_median",
            "display_pi_low_90",
            "display_pi_high_90",
            "record_quality_warning",
            "valuation_date",
        },
        "assessment screen",
    )

    years = (
        assessments.filter(
            pl.col("year_parsed").is_in([config.comparison_year, config.tax_year])
            & (pl.col("market_value") > 0)
        )
        .select("parcel_number", "year_parsed", "market_value")
        .pivot(on="year_parsed", index="parcel_number", values="market_value")
    )
    old_name, new_name = str(config.comparison_year), str(config.tax_year)
    if old_name not in years.columns or new_name not in years.columns:
        raise ValueError(
            f"assessment history must contain {config.comparison_year} and {config.tax_year}"
        )
    years = years.rename({old_name: "old_assessment", new_name: "new_assessment"})

    matched = (
        screen.filter(
            (pl.col("model_family") == "residential")
            & (pl.col("opa_market_value") > 0)
            & (pl.col("display_median") > 0)
        )
        .select(
            "parcel_id",
            "loc_zip5",
            "opa_market_value",
            "display_median",
            "display_pi_low_90",
            "display_pi_high_90",
            "record_quality_warning",
        )
        .join(years, left_on="parcel_id", right_on="parcel_number", how="inner")
        .drop_nulls(["old_assessment", "new_assessment", "display_median"])
        .with_columns(
            pl.col("record_quality_warning").fill_null(True).alias("_data_warning"),
            (pl.col("new_assessment") / pl.col("old_assessment") - 1).alias("_change"),
            (pl.col("old_assessment") / pl.col("display_median")).alias("_old_ratio"),
            (pl.col("new_assessment") / pl.col("display_median")).alias("_new_ratio"),
            (pl.col("old_assessment") / pl.col("display_median")).log().abs().alias("_old_error"),
            (pl.col("new_assessment") / pl.col("display_median")).log().abs().alias("_new_error"),
        )
        .with_columns(
            _direction_expr(config.min_log_direction),
            (
                (pl.col("old_assessment") >= pl.col("display_pi_low_90"))
                & (pl.col("old_assessment") <= pl.col("display_pi_high_90"))
            ).alias("_old_inside"),
            (
                (pl.col("new_assessment") >= pl.col("display_pi_low_90"))
                & (pl.col("new_assessment") <= pl.col("display_pi_high_90"))
            ).alias("_new_inside"),
        )
    )
    if matched.is_empty():
        raise ValueError("no residential properties matched the two assessment rolls")

    benchmark_date_value = screen.select(pl.col("valuation_date").dt.date().max()).item()
    if not isinstance(benchmark_date_value, date):
        raise ValueError("assessment screen has no valuation date")
    benchmark_date = benchmark_date_value.isoformat()

    n = matched.height
    roll_summary = matched.select(
        pl.col("old_assessment").median().alias("old_median"),
        pl.col("new_assessment").median().alias("new_median"),
        pl.col("_change").median().alias("median_change"),
        pl.col("_change").quantile(0.1).alias("p10_change"),
        pl.col("_change").quantile(0.9).alias("p90_change"),
        pl.col("old_assessment").sum().alias("old_total"),
        pl.col("new_assessment").sum().alias("new_total"),
        (pl.col("new_assessment") > pl.col("old_assessment")).sum().alias("n_up"),
        (pl.col("new_assessment") < pl.col("old_assessment")).sum().alias("n_down"),
        (pl.col("new_assessment") == pl.col("old_assessment")).sum().alias("n_same"),
        ((pl.col("new_assessment") - pl.col("old_assessment")) * config.millage)
        .median()
        .alias("median_gross_tax_change"),
    ).to_dicts()[0]

    reliable = matched.filter(~pl.col("_data_warning"))
    n_reliable = reliable.height
    benchmark_values = reliable["display_median"].to_numpy().astype(np.float64)
    old_metrics = _roll_metrics(
        reliable["old_assessment"].to_numpy().astype(np.float64), benchmark_values
    )
    new_metrics = _roll_metrics(
        reliable["new_assessment"].to_numpy().astype(np.float64), benchmark_values
    )
    counts = {
        row["_direction"]: int(row["len"])
        for row in reliable.group_by("_direction").len().to_dicts()
    }
    n_corrective = counts.get("corrective", 0)
    n_widening = counts.get("widening", 0)
    n_no_clear = counts.get("no_clear_change", 0)
    interval = reliable.select(
        pl.col("_old_inside").mean().alias("old_inside"),
        pl.col("_new_inside").mean().alias("new_inside"),
        ((~pl.col("_old_inside")) & pl.col("_new_inside")).mean().alias("entered"),
        (pl.col("_old_inside") & (~pl.col("_new_inside"))).mean().alias("left"),
    ).to_dicts()[0]

    # Stable equal-count tiers based on the independent estimate, not on either
    # assessment roll.  That keeps movement in the outcome from changing the
    # group a property belongs to.
    tiered = reliable.with_columns(
        (
            ((pl.col("display_median").rank(method="ordinal") - 1) * 5 / pl.len())
            .floor()
            .cast(pl.Int8)
            + 1
        ).alias("_tier")
    )
    tier_labels = {
        1: "Cheapest 20%",
        2: "Lower-middle 20%",
        3: "Middle 20%",
        4: "Upper-middle 20%",
        5: "Most expensive 20%",
    }
    tier_rows: list[dict[str, Any]] = []
    for row in (
        tiered.group_by("_tier")
        .agg(
            pl.len().alias("n"),
            pl.col("_change").median().alias("median_change"),
            pl.col("_old_ratio").median().alias("old_ratio"),
            pl.col("_new_ratio").median().alias("new_ratio"),
            (pl.col("_direction") == "corrective").sum().alias("n_corrective"),
            (pl.col("_direction") == "widening").sum().alias("n_widening"),
            (pl.col("_direction") == "no_clear_change").sum().alias("n_no_clear"),
        )
        .sort("_tier")
        .to_dicts()
    ):
        tier_n = int(row["n"])
        tier = int(row["_tier"])
        tier_rows.append(
            {
                "tier": tier,
                "label": tier_labels[tier],
                "n": tier_n,
                "median_change_pct": round(float(row["median_change"]) * 100, 1),
                "old_ratio_pct": round(float(row["old_ratio"]) * 100, 1),
                "new_ratio_pct": round(float(row["new_ratio"]) * 100, 1),
                "corrective_pct": _pct(int(row["n_corrective"]), tier_n),
                "widening_pct": _pct(int(row["n_widening"]), tier_n),
                "no_clear_pct": _pct(int(row["n_no_clear"]), tier_n),
            }
        )

    # ZIP codes are a reproducible geographic view.  They are intentionally not
    # relabeled as neighborhoods, whose boundaries vary by source.
    areas: list[dict[str, Any]] = []
    for row in (
        matched.drop_nulls("loc_zip5")
        .group_by("loc_zip5")
        .agg(
            pl.len().alias("n"),
            (~pl.col("_data_warning")).sum().alias("n_reliable"),
            pl.col("_change").median().alias("median_change"),
            ((pl.col("new_assessment") - pl.col("old_assessment")) * config.millage)
            .median()
            .alias("median_gross_tax_change"),
            pl.col("_data_warning").mean().alias("warning_share"),
            (pl.col("_direction") == "corrective").sum().alias("n_corrective"),
            (pl.col("_direction") == "widening").sum().alias("n_widening"),
            (pl.col("_direction") == "no_clear_change").sum().alias("n_no_clear"),
            pl.col("_old_ratio").filter(~pl.col("_data_warning")).median().alias("old_ratio"),
            pl.col("_new_ratio").filter(~pl.col("_data_warning")).median().alias("new_ratio"),
        )
        .filter(pl.col("n") >= config.min_area_n)
        .sort("median_change", descending=True)
        .to_dicts()
    ):
        area_reliable = int(row["n_reliable"])
        areas.append(
            {
                "zip": str(row["loc_zip5"]),
                "n": int(row["n"]),
                "n_reliable": area_reliable,
                "median_change_pct": round(float(row["median_change"]) * 100, 1),
                "median_gross_tax_change_usd": round(float(row["median_gross_tax_change"])),
                "corrective_pct": _pct(int(row["n_corrective"]), area_reliable),
                "widening_pct": _pct(int(row["n_widening"]), area_reliable),
                "no_clear_pct": _pct(int(row["n_no_clear"]), area_reliable),
                "data_warning_pct": round(float(row["warning_share"]) * 100, 1),
                "old_ratio_pct": round(float(row["old_ratio"]) * 100, 1),
                "new_ratio_pct": round(float(row["new_ratio"]) * 100, 1),
            }
        )

    # Race is audit context, never a valuation input.  The source describes the
    # majority racial composition of a census tract, not the race of a property
    # owner or resident.  Keep the three prespecified, citywide groups used by
    # the project's other fairness diagnostics so that small or heterogeneous
    # categories are not promoted into unstable release-day claims.
    race_context: list[dict[str, Any]] = []
    if demographics is not None:
        _required(
            demographics,
            {"parcel_id", "acs_majority_race"},
            "demographic audit context",
        )
        by_race = (
            reliable.join(
                demographics.select("parcel_id", "acs_majority_race").unique("parcel_id"),
                on="parcel_id",
                how="left",
            )
            .filter(pl.col("acs_majority_race").is_in(list(RACE_CONTEXT_LABELS)))
            .group_by("acs_majority_race")
            .agg(
                pl.len().alias("n"),
                pl.col("_change").median().alias("median_change"),
                pl.col("_old_ratio").median().alias("old_ratio"),
                pl.col("_new_ratio").median().alias("new_ratio"),
                (pl.col("_direction") == "corrective").sum().alias("n_corrective"),
                (pl.col("_direction") == "widening").sum().alias("n_widening"),
                (pl.col("_direction") == "no_clear_change").sum().alias("n_no_clear"),
            )
        )
        rows_by_group = {str(row["acs_majority_race"]): row for row in by_race.to_dicts()}
        for group, label in RACE_CONTEXT_LABELS.items():
            row = rows_by_group.get(group)
            if row is None or int(row["n"]) < config.min_area_n:
                continue
            group_n = int(row["n"])
            race_context.append(
                {
                    "group": group,
                    "label": label,
                    "n": group_n,
                    "median_change_pct": round(float(row["median_change"]) * 100, 1),
                    "old_ratio_pct": round(float(row["old_ratio"]) * 100, 1),
                    "new_ratio_pct": round(float(row["new_ratio"]) * 100, 1),
                    "corrective_pct": _pct(int(row["n_corrective"]), group_n),
                    "widening_pct": _pct(int(row["n_widening"]), group_n),
                    "no_clear_pct": _pct(int(row["n_no_clear"]), group_n),
                }
            )

    q1, q5 = tier_rows[0], tier_rows[-1]
    report = {
        "tax_year": config.tax_year,
        "comparison_year": config.comparison_year,
        "status": "provisional",
        "effective_date": config.effective_date,
        "benchmark_date": benchmark_date,
        "sales_cutoff": config.sales_cutoff,
        "scope": "Single-family residential properties with positive values in both rolls",
        "n_properties": n,
        "roll": {
            "old_median_usd": round(float(roll_summary["old_median"])),
            "new_median_usd": round(float(roll_summary["new_median"])),
            "median_change_pct": round(float(roll_summary["median_change"]) * 100, 1),
            "p10_change_pct": round(float(roll_summary["p10_change"]) * 100, 1),
            "p90_change_pct": round(float(roll_summary["p90_change"]) * 100, 1),
            "total_change_pct": round(
                (float(roll_summary["new_total"]) / float(roll_summary["old_total"]) - 1) * 100,
                1,
            ),
            "increased_pct": _pct(int(roll_summary["n_up"]), n),
            "decreased_pct": _pct(int(roll_summary["n_down"]), n),
            "unchanged_pct": _pct(int(roll_summary["n_same"]), n),
            "median_gross_tax_change_usd": round(float(roll_summary["median_gross_tax_change"])),
        },
        "correction": {
            "n_reliable": n_reliable,
            "n_data_warning": n - n_reliable,
            "data_warning_pct": _pct(n - n_reliable, n),
            "corrective_pct": _pct(n_corrective, n_reliable),
            "widening_pct": _pct(n_widening, n_reliable),
            "no_clear_pct": _pct(n_no_clear, n_reliable),
            "net_corrective_pp": round(
                _pct(n_corrective, n_reliable) - _pct(n_widening, n_reliable), 1
            ),
            "old_inside_interval_pct": round(float(interval["old_inside"]) * 100, 1),
            "new_inside_interval_pct": round(float(interval["new_inside"]) * 100, 1),
            "entered_interval_pct": round(float(interval["entered"]) * 100, 1),
            "left_interval_pct": round(float(interval["left"]) * 100, 1),
            "direction_threshold_pct": round(config.min_log_direction * 100, 1),
        },
        "vertical_equity": {
            "old_gap_pp": round(abs(q1["old_ratio_pct"] - q5["old_ratio_pct"]), 1),
            "new_gap_pp": round(abs(q1["new_ratio_pct"] - q5["new_ratio_pct"]), 1),
            "gap_change_pp": round(
                abs(q1["new_ratio_pct"] - q5["new_ratio_pct"])
                - abs(q1["old_ratio_pct"] - q5["old_ratio_pct"]),
                1,
            ),
            "verdict": (
                "worsened"
                if abs(q1["new_ratio_pct"] - q5["new_ratio_pct"])
                > abs(q1["old_ratio_pct"] - q5["old_ratio_pct"])
                else "improved"
            ),
            "prd": {"old": old_metrics["prd"], "new": new_metrics["prd"]},
            "prb": {"old": old_metrics["prb"], "new": new_metrics["prb"]},
            "vei": {"old": old_metrics["vei"], "new": new_metrics["vei"]},
            "basis": "Assessment divided by the same independent model benchmark",
        },
        "uniformity": {
            "old_cod": old_metrics["cod"],
            "new_cod": new_metrics["cod"],
            "verdict": (
                "improved"
                if old_metrics["cod"] is not None
                and new_metrics["cod"] is not None
                and new_metrics["cod"] < old_metrics["cod"]
                else "worsened"
            ),
        },
        "tiers": tier_rows,
        "areas": areas,
        "race_context": race_context,
    }
    if locations is not None:
        report["boundary_transect"] = build_boundary_transect(matched, locations, boundary_transect)
    return report
