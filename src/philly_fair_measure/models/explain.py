"""Per-property assessment explanations via exact TreeSHAP.

The "what goes into your assessment" layer for the public dashboard. LightGBM's
``pred_contrib=True`` is exact TreeSHAP (Lundberg et al.) and comes free with the
booster — no ``shap`` dependency; for stack runs, CatBoost's native ShapValues
blend in with the persisted stack weight, so the drivers explain the stacked
point exactly. It decomposes the prediction additively into a
base value plus one signed contribution per feature; this module ranks those,
attaches plain-language labels and category groups, and converts them to
approximate signed dollar effects for a lay audience.

State-of-the-art product lesson (Cook County's Home Value Report): do NOT show a
homeowner a raw SHAP force plot — surface a few translated "top drivers" and a
category-level "what matters most" view. ``plain_language`` and
``Explanation.by_group`` are those two views.

Honesty constraints baked in:

- Contributions decompose the booster's **reference-frame log price** — before
  the isotonic vertical calibration (a monotone post-adjustment) and before the
  date/time move. Per-driver dollars are anchored to the calibrated display
  value so they're proportional to the shown number, but value is multiplicative
  in log space, so the drivers are approximate and do NOT sum exactly to
  (value - base). Treat them as "roughly how much this factor moved your value."
- Location is carried by several correlated features (kNN surface, block rolls,
  market area); TreeSHAP splits credit among them. ``by_group`` re-aggregates to
  a faithful category level, which is what a homeowner should see first.
- This explains the model, faithfully. It is not a fairness certificate — an
  explanation that looks reasonable can still sit on a biased number (the
  "fairwashing" risk), so the per-home panel must never be shown as evidence
  that an assessment is *fair*; the ratio-study diagnostics carry that claim.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure.models.baseline import _encode, apply_vertical_calibration

logger = logging.getLogger(__name__)

_HOME = "Home characteristics"
_LOCATION = "Location & neighborhood"
_SALES = "Recent nearby sales"
_DISTRESS = "Distress & condition"
_ACCESS = "Access & amenities"
_OTHER = "Other factors"

# (friendly label, category) for the model features. Anything unmapped falls
# back to a prettified code under "Other factors".
FEATURE_LABELS: dict[str, tuple[str, str]] = {
    "char_livable_area": ("living area", _HOME),
    "char_lot_area": ("lot size", _HOME),
    "char_frontage": ("lot frontage", _HOME),
    "char_depth": ("lot depth", _HOME),
    "char_beds": ("bedrooms", _HOME),
    "char_baths": ("bathrooms", _HOME),
    "char_rooms": ("total rooms", _HOME),
    "char_stories": ("number of stories", _HOME),
    "char_year_built": ("year built", _HOME),
    "char_garage_spaces": ("garage spaces", _HOME),
    "char_fireplaces": ("fireplaces", _HOME),
    "char_footprint_sqft": ("building footprint", _HOME),
    "char_footprint_estimated_floors": ("footprint-estimated floors", _HOME),
    "char_footprint_gross_sqft": ("footprint-estimated gross area", _HOME),
    "char_livable_to_footprint_gross_ratio": ("recorded-area consistency", _HOME),
    "char_footprint_story_gap": ("story-count consistency", _HOME),
    "char_area_conflict": ("conflicting building area records", _HOME),
    "evt_n_completed_permits_5y_before": ("completed recent permits", _DISTRESS),
    "evt_n_active_permits_at_sale": ("active permitted work", _DISTRESS),
    "evt_n_completed_reno_permits_5y_before": ("completed renovation permits", _DISTRESS),
    "evt_n_active_reno_permits_at_sale": ("active renovation permits", _DISTRESS),
    "evt_n_active_change_occupancy_at_sale": ("active occupancy-changing work", _DISTRESS),
    "char_category": ("property type", _HOME),
    "char_building_type": ("building type", _HOME),
    "char_style": ("architectural style", _HOME),
    "char_era": ("construction era", _HOME),
    "char_construction": ("construction material", _HOME),
    "char_basement": ("basement", _HOME),
    "char_central_air": ("central air", _HOME),
    "char_heater": ("heating type", _HOME),
    "char_quality_grade_raw": ("quality grade", _HOME),
    "char_view": ("view", _HOME),
    "char_topography": ("lot topography", _HOME),
    "char_exterior_condition": ("exterior condition (on record)", _DISTRESS),
    "char_interior_condition": ("interior condition (on record)", _DISTRESS),
    "shp_parcel_area_m2": ("parcel area", _HOME),
    "shp_parcel_perimeter_m": ("parcel shape", _HOME),
    "shp_n_linked_parcels": ("adjoining owned parcels", _HOME),
    "shp_linked_lot_area_m2": ("combined lot area", _HOME),
    "mkt_block_roll_mean_price": ("recent sale prices on your block", _SALES),
    "mkt_block_roll_ppsf": ("recent price per sq ft on your block", _SALES),
    "mkt_block_roll_n": ("number of recent block sales", _SALES),
    "mkt_knn_log_ppsf": ("nearby recent sale prices", _SALES),
    "mkt_knn_n": ("number of nearby recent sales", _SALES),
    "mkt_knn_mean_dist_m": ("distance to comparable sales", _SALES),
    "mkt_knn_price_anchor_log": ("nearby prices scaled to this home's size", _SALES),
    "mkt_newbuild_price_anchor_log": ("new-construction prices at this home's size", _SALES),
    "char_new_build": ("newly built home", _HOME),
    "mkt_knn_footprint_price_anchor_log": ("nearby prices scaled to the footprint", _SALES),
    "mkt_newbuild_knn_log_ppsf": ("nearby sales of newly built homes", _SALES),
    "mkt_newbuild_knn_n": ("number of nearby new-construction sales", _SALES),
    "mkt_newbuild_knn_mean_dist_m": ("distance to new-construction sales", _SALES),
    "mkt_newbuild_premium": ("local new-construction premium", _SALES),
    "mkt_area_level_log_ppsf": ("neighborhood price level", _LOCATION),
    "mkt_parcel_prev_price": ("your home's prior sale price", _SALES),
    "mkt_parcel_prev_log_price_ref": ("your home's prior sale (adjusted)", _SALES),
    "mkt_parcel_n_prior_sales": ("your home's prior sales", _SALES),
    "mkt_parcel_days_since_prev": ("time since your last sale", _SALES),
    "loc_market_area": ("neighborhood (market area)", _LOCATION),
    "loc_district": ("assessment district", _LOCATION),
    "loc_zip5": ("ZIP code", _LOCATION),
    "loc_ward": ("ward", _LOCATION),
    "loc_census_tract_raw": ("census tract", _LOCATION),
    "loc_lon": ("location (longitude)", _LOCATION),
    "loc_lat": ("location (latitude)", _LOCATION),
    "loc_street_class": ("street type", _ACCESS),
    "prox_dist_rapid_transit_m": ("distance to rapid transit", _ACCESS),
    "prox_dist_regional_rail_m": ("distance to regional rail", _ACCESS),
    "prox_dist_park_m": ("distance to a park", _ACCESS),
    "prox_dist_expressway_m": ("distance to an expressway", _ACCESS),
    "prox_dist_arterial_m": ("distance to a major road", _ACCESS),
    "prox_n_bus_stops_800m": ("nearby bus stops", _ACCESS),
    "prox_dist_bike_network_m": ("distance to bike network", _ACCESS),
    "prox_parcel_density_400m": ("neighborhood density", _LOCATION),
    "prox_dist_vacant_land_m": ("distance to vacant land", _DISTRESS),
    "dist_tax_delinquent": ("tax delinquency", _DISTRESS),
    "dist_tax_years_owed": ("years of tax owed", _DISTRESS),
    "dist_tax_total_due": ("tax balance due", _DISTRESS),
    "dist_sheriff_sale": ("sheriff-sale history", _DISTRESS),
    "evt_n_permits_5y_before": ("recent building permits", _DISTRESS),
    "evt_days_since_last_permit": ("time since last permit", _DISTRESS),
    "evt_n_violations_5y_before": ("recent code violations", _DISTRESS),
    "evt_n_open_violations_at_sale": ("open code violations", _DISTRESS),
    "evt_n_severe_violations_5y_before": ("serious code violations", _DISTRESS),
    "evt_n_demolitions_before": ("nearby demolitions", _DISTRESS),
    "evt_n_vacant_complaints_5y_before": ("vacancy complaints", _DISTRESS),
    "ten_rental_license_at_sale": ("rental license", _HOME),
    "ten_rental_units": ("rental units", _HOME),
    "ten_owner_occupied_at_sale": ("owner-occupied (homestead)", _HOME),
    # condo-model features (the condo run shares this explain layer)
    "char_unit_area": ("unit size", _HOME),
    "char_floor": ("floor", _HOME),
    "unit_area_share": ("share of the building", _HOME),
    "bldg_n_units": ("units in the building", _LOCATION),
    "mkt_bldg_roll_mean_price": ("recent sale prices in your building", _SALES),
    "mkt_bldg_roll_ppsf": ("recent price per sq ft in your building", _SALES),
    "mkt_bldg_roll_n": ("number of recent sales in your building", _SALES),
    # fin_ (mortgage-history) features are intentionally not surfaced — see
    # _SUPPRESSED_PREFIXES.
}

_PREFIXES = ("char_", "mkt_", "loc_", "prox_", "dist_", "evt_", "ten_", "fin_", "shp_")

# Feature families kept in the model but NOT surfaced as personal value drivers.
# Mortgage-history signals (fin_) are entangled with credit access — the very
# channel the cash/financed equity work identified behind the regressive pattern
# — so "days since your last mortgage adds $X to your value" is both opaque and
# ethically fraught to show a homeowner, even though it's a valid market input.
_SUPPRESSED_PREFIXES = ("fin_",)

# Only features whose raw value is self-explanatory to a homeowner get shown with
# a value; everything else (log price surfaces, tract codes, encoded conditions)
# is shown as a labelled driver + dollar effect only — a raw "-1.21192" erodes
# trust. Empty unit = the number stands alone (e.g. a year).
_VALUE_UNITS: dict[str, str] = {
    "char_livable_area": "sq ft",
    "char_lot_area": "sq ft",
    "char_beds": "beds",
    "char_baths": "baths",
    "char_rooms": "rooms",
    "char_stories": "stories",
    "char_year_built": "",
    "char_garage_spaces": "garage spaces",
    "char_fireplaces": "fireplaces",
    "char_unit_area": "sq ft",
    "char_floor": "",
}


def _label(feature: str) -> tuple[str, str]:
    if feature in FEATURE_LABELS:
        return FEATURE_LABELS[feature]
    name = feature
    for pre in _PREFIXES:
        if name.startswith(pre):
            name = name[len(pre) :]
            break
    return name.replace("_", " "), _OTHER


def _fmt_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:g}"
    return str(value)


_SINGULAR_UNITS: dict[str, str] = {
    "beds": "bed",
    "baths": "bath",
    "rooms": "room",
    "stories": "story",
    "fireplaces": "fireplace",
    "garage spaces": "garage space",
}


def display_value(feature: str, value: object) -> str | None:
    """Homeowner-facing rendering of a driver's recorded value ("1,120 sq ft"),
    or None when the raw number is model-internal (log surfaces, tract codes,
    epoch days) — the _VALUE_UNITS gate. Consumers outside plain_language (the
    dashboard API) must use this rather than str(raw_value)."""
    if value is None or feature not in _VALUE_UNITS:
        return None
    if feature == "char_year_built" and isinstance(value, (int, float)):
        return str(int(value))  # a year, not a quantity — no thousands separator
    unit = _VALUE_UNITS[feature]
    if isinstance(value, (int, float)) and float(value) == 1.0:
        unit = _SINGULAR_UNITS.get(unit, unit)  # "1 bath", not "1 baths"
    return f"{_fmt_value(value)} {unit}".strip()


# OPA's published code meanings (OPA data dictionary, opa_properties_public).
# Only codes the city documents are decoded — everything else stays raw rather
# than risk an invented meaning on a civic site.
_CONDITION_CODES: dict[str, str] = {
    "0": "not applicable",
    "1": "newer construction",
    "2": "rehabilitated",
    "3": "above average",
    "4": "average",
    "5": "below average",
    "6": "vacant",
    "7": "sealed / structurally compromised",
}
_BASEMENT_CODES: dict[str, str] = {
    "0": "none",
    "A": "full, finished",
    "B": "full, semi-finished",
    "C": "full, unfinished",
    "D": "full, unknown finish",
    "E": "partial, finished",
    "F": "partial, semi-finished",
    "G": "partial, unfinished",
    "H": "partial, unknown finish",
    "I": "unknown size, finished",
    "J": "unknown size, unfinished",
}
_YES_NO = {"Y": "yes", "N": "no", "1": "yes", "0": "no"}

RECORDED_CODES: dict[str, dict[str, str]] = {
    "char_exterior_condition": _CONDITION_CODES,
    "char_interior_condition": _CONDITION_CODES,
    "char_basement": _BASEMENT_CODES,
    "char_central_air": _YES_NO,
}


def decode_recorded(feature: str, value: object) -> str | None:
    """City-code translation for a recorded fact ("4" -> "average (code 4)"),
    or None when the code isn't in OPA's published dictionary."""
    if value is None:
        return None
    raw = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    raw = raw.strip().upper()
    meaning = RECORDED_CODES.get(feature, {}).get(raw)
    if meaning is None:
        return None
    if feature == "char_central_air":
        return meaning
    return f"{meaning} (code {raw})"


@dataclass(frozen=True)
class Driver:
    """One feature's signed effect on a property's estimated value."""

    feature: str
    label: str
    group: str
    raw_value: object
    contribution: float  # TreeSHAP contribution, log-price (reference frame)
    dollar_effect: float  # approx signed dollars, anchored to the display value

    @property
    def raises(self) -> bool:
        return self.contribution >= 0


@dataclass(frozen=True)
class Explanation:
    """A property's value plus its ranked drivers (most influential first)."""

    value: float  # calibrated reference-frame dollar estimate
    base_value: float  # model baseline before any feature (typical home)
    drivers: list[Driver]

    def top(self, n: int = 5) -> list[Driver]:
        return self.drivers[:n]

    def by_group(self) -> list[tuple[str, float]]:
        """Category-level dollar effects (the 'what matters most' view), the
        faithful way to present correlated features like the location signals."""
        agg: dict[str, float] = {}
        for d in self.drivers:
            agg[d.group] = agg.get(d.group, 0.0) + d.dollar_effect
        return sorted(agg.items(), key=lambda kv: abs(kv[1]), reverse=True)

    def anchored_to(self, value: float) -> Explanation:
        """Rescale per-driver dollars to a different display value (e.g. the
        report's Bayesian headline) while leaving the log-space contributions —
        and therefore the ranking — untouched. The dollars stay approximate."""
        drivers = [
            replace(d, dollar_effect=value * (1.0 - float(np.exp(-d.contribution))))
            for d in self.drivers
        ]
        return replace(self, value=value, drivers=drivers)


def explain(run_dir: Path, df: pl.DataFrame) -> list[Explanation]:
    """One Explanation per row of ``df`` (which must carry the run's features).

    Explains the run's POINT estimate. For stack runs both arms contribute
    SHAP values on the same feature order and the log-space contributions
    blend with the persisted convex weight — the explained value stays exactly
    what `score_point` serves. Pre-stack runs take the LightGBM-only path.
    """
    import lightgbm as lgb

    from philly_fair_measure.models.scoring import prepare_model_frame

    df = prepare_model_frame(run_dir, df)
    booster = lgb.Booster(model_file=str(run_dir / "model_lightgbm.txt"))
    mappings: dict[str, dict[str, int]] = json.loads(
        (run_dir / "categorical_mappings.json").read_text()
    )
    params = json.loads((run_dir / "params.json").read_text())
    numeric: list[str] = list(params["numeric_features"])
    categorical: list[str] = list(params["categorical_features"])
    features = numeric + categorical

    x = _encode(df, mappings, numeric, categorical)
    contribs = np.asarray(booster.predict(x, pred_contrib=True), dtype=np.float64)  # (n, F+1)
    stack_path = run_dir / "stack.json"
    if stack_path.exists():
        from catboost import CatBoostRegressor, Pool

        from philly_fair_measure.models.baseline import catboost_frame

        cat_model = CatBoostRegressor()
        cat_model.load_model(str(run_dir / "model_catboost.cbm"))
        pool = Pool(
            catboost_frame(df, numeric, categorical),
            cat_features=list(range(len(numeric), len(numeric) + len(categorical))),
        )
        cat_contribs = np.asarray(
            cat_model.get_feature_importance(data=pool, type="ShapValues"), dtype=np.float64
        )  # (n, F+1), same feature order, last column = expected value
        w = float(json.loads(stack_path.read_text())["weight_lightgbm"])
        contribs = w * contribs + (1 - w) * cat_contribs
    raw_log = contribs.sum(axis=1)  # base + drivers = the raw point, both arms
    cal_path = run_dir / "vertical_calibration.json"
    cal_log: npt.NDArray[np.float64] = (
        apply_vertical_calibration(raw_log, json.loads(cal_path.read_text()))
        if cal_path.exists()
        else np.asarray(raw_log, dtype=np.float64)
    )
    values = np.asarray(np.exp(cal_log), dtype=np.float64)

    present = set(df.columns)
    out: list[Explanation] = []
    for i in range(df.height):
        value = float(values[i])
        drivers = []
        for j, feat in enumerate(features):
            contribution = float(contribs[i, j])
            if contribution == 0.0 or feat.startswith(_SUPPRESSED_PREFIXES):
                continue
            label, group = _label(feat)
            raw = df[feat][i] if feat in present else None
            dollar = value * (1.0 - float(np.exp(-contribution)))
            drivers.append(Driver(feat, label, group, raw, contribution, dollar))
        drivers.sort(key=lambda d: abs(d.contribution), reverse=True)
        base = float(np.exp(contribs[i, -1]))
        out.append(Explanation(value=value, base_value=base, drivers=drivers))
    return out


# Recorded characteristics a homeowner can contest — the appeal grounds. Location,
# market, parcel-geometry and event-record features are excluded: they aren't
# "facts about my house" an owner corrects (and OPA's own record is the source).
CORRECTABLE = frozenset(
    {
        "char_livable_area",
        "char_lot_area",
        "char_beds",
        "char_baths",
        "char_rooms",
        "char_stories",
        "char_year_built",
        "char_garage_spaces",
        "char_fireplaces",
        "char_exterior_condition",
        "char_interior_condition",
        "char_basement",
        "char_central_air",
        "char_construction",
        "char_quality_grade_raw",
        "char_unit_area",
        "char_floor",
    }
)

# "Looks unusual, verify first" bounds for numeric characteristics — deliberately
# generous; outside → flagged for the owner to check, not asserted as wrong.
_PLAUSIBLE: dict[str, tuple[float, float]] = {
    "char_livable_area": (500.0, 15000.0),
    "char_lot_area": (300.0, 100000.0),
    "char_beds": (1.0, 12.0),
    "char_baths": (1.0, 12.0),
    "char_rooms": (1.0, 30.0),
    "char_stories": (1.0, 6.0),
    "char_year_built": (1820.0, 2026.0),
}


@dataclass(frozen=True)
class AppealPoint:
    """A recorded characteristic worth verifying for an appeal."""

    feature: str
    label: str
    recorded_value: object
    dollar_effect: float  # the recorded value's effect on the estimate vs typical
    implausible: bool  # recorded value falls outside the generous plausible range


def _is_implausible(feature: str, value: object) -> bool:
    bounds = _PLAUSIBLE.get(feature)
    if bounds is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    lo, hi = bounds
    return not lo <= value <= hi


def appeal_points(
    explanation: Explanation, characteristics: dict[str, object]
) -> list[AppealPoint]:
    """Correctable recorded facts that drive the estimate, most-suspect first
    (implausible values, then largest effect). The appeal on-ramp: a wrong entry
    here is a specific, documentable correction to request."""
    points = []
    for d in explanation.drivers:
        if d.feature not in CORRECTABLE:
            continue
        value = characteristics.get(d.feature, d.raw_value)
        points.append(
            AppealPoint(
                d.feature, d.label, value, d.dollar_effect, _is_implausible(d.feature, value)
            )
        )
    points.sort(key=lambda p: (not p.implausible, -abs(p.dollar_effect)))
    return points


def plain_language(explanation: Explanation, n: int = 5) -> list[str]:
    """The top ``n`` drivers as lay-readable sentences."""
    lines = []
    for d in explanation.top(n):
        verb = "adds about" if d.raises else "reduces value by about"
        detail = ""
        if d.feature in _VALUE_UNITS and d.raw_value is not None:
            unit = _VALUE_UNITS[d.feature]
            shown = _fmt_value(d.raw_value)
            detail = f" ({shown} {unit})" if unit else f" ({shown})"
        lines.append(f"{d.label.capitalize()}{detail} {verb} ${abs(d.dollar_effect):,.0f}.")
    return lines
