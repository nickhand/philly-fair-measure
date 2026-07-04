"""Static property report: the appeal-packet renderer (`philly report`).

The founding deliverable's last mile: everything the pipeline knows about one
property, rendered into a single self-contained HTML file an owner could
print for an assessment appeal — OPA value vs the model's 90% interval,
comparable sales, the identical-twin uniformity exhibit (PA's uniformity
clause makes assessment-vs-comparable-assessments a first-class appeal
argument), aerial-change / complaint / tenure evidence, assessment and sale
history, and data-vintage provenance.

Informational only, not legal advice — the report says so. Sections render
only when their evidence exists; condo parcels get the screen row and unit
context (no comps/twins yet).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from philly_assessments import config
from philly_assessments.ingest.manifests import read_derived_manifest

logger = logging.getLogger(__name__)


@dataclass
class ReportData:
    parcel_id: str
    screen: dict
    characteristics: dict
    comps: pl.DataFrame | None = None
    twins: pl.DataFrame | None = None
    assessment_history: pl.DataFrame | None = None
    sale_history: pl.DataFrame | None = None
    provenance: dict = field(default_factory=dict)


def gather(parcel_id: str, data_dir: Path | None = None) -> ReportData:
    root = data_dir if data_dir is not None else config.data_dir()
    screen_path = root / "marts" / "assessment_screen.parquet"
    row = (
        pl.scan_parquet(screen_path).filter(pl.col("parcel_id") == parcel_id).collect()
    )
    if not row.height:
        raise KeyError(f"parcel {parcel_id} not in the assessment screen")
    screen = row.to_dicts()[0]
    is_condo = screen.get("model_family") == "condo"

    features_path = root / "marts" / (
        "condo_assessment_features.parquet" if is_condo else "assessment_features.parquet"
    )
    feat = (
        pl.scan_parquet(features_path).filter(pl.col("parcel_id") == parcel_id).collect()
    )
    characteristics = feat.to_dicts()[0] if feat.height else {}

    comps = None
    twins = None
    if not is_condo:
        try:
            from philly_assessments.models.comps import find_comps

            comps = find_comps(parcel_id, data_dir, k=8).comps
        except Exception:  # noqa: BLE001 — comps are optional evidence
            logger.warning("comps unavailable for %s", parcel_id, exc_info=True)
        if screen.get("twin_n") is not None and characteristics:
            from philly_assessments.validation.opa import strict_twin_key

            features = pl.scan_parquet(features_path)
            key = (
                pl.DataFrame([characteristics])
                .select(strict_twin_key().alias("k"))["k"][0]
            )
            twins = (
                features.filter(strict_twin_key() == key)
                .select("parcel_id", "address", "opa_market_value")
                .collect()
                .sort("opa_market_value", descending=True)
            )

    assessments_path = root / "staged" / "assessments.parquet"
    assessment_history = None
    if assessments_path.exists():
        assessment_history = (
            pl.scan_parquet(assessments_path)
            .filter(
                (pl.col("parcel_number") == parcel_id)
                & pl.col("year_parsed").is_not_null()
                & (pl.col("market_value").fill_null(0) > 0)
            )
            .select(pl.col("year_parsed").alias("year"), "market_value")
            .sort("year")
            .collect()
        )

    validity_path = root / "marts" / "sale_validity.parquet"
    sale_history = None
    if validity_path.exists():
        sale_history = (
            pl.scan_parquet(validity_path)
            .filter(
                (pl.col("parcel_id") == parcel_id) & pl.col("sale_date").is_not_null()
            )
            .select("sale_date", "sale_price", "deed_kind", "validity_status")
            .sort("sale_date", descending=True)
            .head(10)
            .collect()
        )

    manifest = read_derived_manifest(screen_path)
    provenance = {
        "screen_built": manifest.built_at.strftime("%Y-%m-%d %H:%M UTC"),
        "inputs": [i.dataset for i in manifest.inputs],
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return ReportData(
        parcel_id=parcel_id,
        screen=screen,
        characteristics=characteristics,
        comps=comps,
        twins=twins,
        assessment_history=assessment_history,
        sale_history=sale_history,
        provenance=provenance,
    )


def _fmt_money(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return html.escape(str(v))


_FLAG_LABELS = {
    "over_assessed_candidate": ("Over-assessment candidate", "#b91c1c"),
    "under_assessed_candidate": ("Under-assessment candidate", "#1d4ed8"),
    "within_range": ("Within the model's range", "#15803d"),
    "no_assessment": ("No assessment on record", "#6b7280"),
}

_CSS = """
body { font: 14px/1.5 -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
       color: #1f2937; max-width: 820px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.5rem; margin-bottom: 0; }
h2 { font-size: 1.05rem; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;
     margin-top: 2rem; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #e5e7eb; }
th { color: #6b7280; font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.flag { display: inline-block; padding: 2px 10px; border-radius: 10px;
        color: white; font-weight: 600; font-size: 13px; }
.kv { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 2px 16px; }
.kv div { padding: 2px 0; } .kv b { color: #6b7280; font-weight: 600;
      display: block; font-size: 11px; text-transform: uppercase; }
.note { color: #6b7280; font-size: 12px; }
.hl { background: #fef3c7; }
@media print { body { margin: 0.5rem auto; } }
"""


def _history_svg(history: pl.DataFrame) -> str:
    if history is None or history.height < 2:
        return ""
    years = history["year"].to_list()
    values = history["market_value"].to_list()
    w, h, pad = 760, 120, 28
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = []
    for i, (_, v) in enumerate(zip(years, values, strict=True)):
        x = pad + i * (w - 2 * pad) / max(1, len(years) - 1)
        y = h - pad - (v - lo) / span * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg width="{w}" height="{h}" role="img">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="#1d4ed8" stroke-width="2"/>'
        f'<text x="{pad}" y="{h - 6}" font-size="11" fill="#6b7280">{years[0]}</text>'
        f'<text x="{w - pad}" y="{h - 6}" font-size="11" fill="#6b7280" '
        f'text-anchor="end">{years[-1]}</text>'
        f'<text x="{pad}" y="14" font-size="11" fill="#6b7280">'
        f"{_fmt_money(lo)} – {_fmt_money(hi)}</text></svg>"
    )


def _evidence_rows(s: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if s.get("twin_n"):
        rows.append(
            (
                "Identical-twin uniformity",
                f"{int(s['twin_n'])} homes on this block are identical in every "
                f"recorded respect; this assessment is "
                f"{(s['opa_vs_twin_median'] - 1) * 100:+.1f}% vs their median",
            )
        )
    if s.get("aerial_change_score") is not None:
        verdict = "ABOVE" if s.get("aerial_change_flag") else "below"
        rows.append(
            (
                f"Aerial change ({s.get('aerial_pair', '?').replace('_', ' ')})",
                f"change score {s['aerial_change_score']:.2f}, {verdict} the "
                "quiet-parcel threshold",
            )
        )
    if s.get("evt_n_vacant_complaints_5y_before"):
        days = s.get("evt_vacant_complaint_days_since")
        recency = f"; most recent {days / 365.25:.1f}y ago" if days else ""
        rows.append(
            (
                "Vacancy complaints",
                f"{int(s['evt_n_vacant_complaints_5y_before'])} in the last 5 years"
                + recency,
            )
        )
    if s.get("evt_n_unpermitted_work_complaints_5y_before"):
        rows.append(
            (
                "Unpermitted-work complaints",
                f"{int(s['evt_n_unpermitted_work_complaints_5y_before'])} in the last 5 years",
            )
        )
    if s.get("dist_tax_delinquent"):
        rows.append(("Tax delinquency", "currently delinquent per the city roll"))
    if s.get("ten_rental_license_at_sale"):
        rows.append(("Rental license", "active rental license on this parcel"))
    if s.get("shp_n_linked_parcels"):
        rows.append(
            (
                "Linked parcels (same owner, adjacent)",
                f"{int(s['shp_n_linked_parcels'])} — house + side-yard style assemblage",
            )
        )
    if s.get("bldg_n_units"):
        rows.append(("Condo building", f"{int(s['bldg_n_units'])} units in the building"))
    return rows


def render_html(data: ReportData) -> str:
    s = data.screen
    c = data.characteristics
    label, color = _FLAG_LABELS.get(s.get("assessment_flag") or "", ("—", "#6b7280"))
    interval_note = (
        "posterior predictive interval (Bayesian model)"
        if s.get("interval_method") == "bayesian_posterior"
        else "spatially weighted conformal interval"
    )

    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(str(s.get('address') or data.parcel_id))}</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(str(s.get('address') or '?'))}</h1>",
        f"<p class='note'>OPA parcel {data.parcel_id} · {_fmt(s.get('char_category'))}"
        f" · report generated {data.provenance.get('generated', '')}</p>",
        f"<p><span class='flag' style='background:{color}'>{label}</span></p>",
        "<h2>Assessment vs model</h2><div class='kv'>",
        f"<div><b>OPA market value</b>{_fmt_money(s.get('opa_market_value'))}</div>",
        f"<div><b>Model estimate</b>{_fmt_money(s.get('model_median'))}</div>",
        f"<div><b>90% interval</b>{_fmt_money(s.get('model_pi_low_90'))} – "
        f"{_fmt_money(s.get('model_pi_high_90'))}</div>",
        f"<div><b>OPA / model</b>{_fmt(s.get('opa_vs_model_ratio'))}</div>",
        f"<div><b>Disagreement z</b>{_fmt(s.get('screen_z'))}</div>",
        "</div>",
        f"<p class='note'>Interval: {interval_note}. The estimate comes from a "
        "public-data model trained on validated arms-length sales; it inherits "
        "the city roll's characteristic errors and cannot see interior condition.</p>",
        "<h2>Recorded characteristics (per the OPA roll)</h2><div class='kv'>",
    ]
    char_fields = [
        ("Livable area", "char_livable_area"),
        ("Lot area", "char_lot_area"),
        ("Style", "char_style"),
        ("Stories", "char_stories"),
        ("Year built", "char_year_built"),
        ("Beds", "char_beds"),
        ("Baths", "char_baths"),
        ("Exterior condition", "char_exterior_condition"),
        ("Interior condition", "char_interior_condition"),
        ("Quality grade", "char_quality_grade_raw"),
    ]
    for label_, key in char_fields:
        source = c if key in c else s
        parts.append(f"<div><b>{label_}</b>{_fmt(source.get(key))}</div>")
    parts.append("</div>")
    parts.append(
        "<p class='note'>Note: OPA does not inspect interiors; the interior "
        "condition code matches the exterior code on 82% of residential parcels "
        "and rarely changes even after major renovation permits.</p>"
    )

    evidence = _evidence_rows(s)
    if evidence:
        parts.append("<h2>Evidence summary</h2><table>")
        for name, detail in evidence:
            parts.append(f"<tr><th>{html.escape(name)}</th><td>{html.escape(detail)}</td></tr>")
        parts.append("</table>")

    if data.twins is not None and data.twins.height >= 2:
        parts.append(
            "<h2>Uniformity exhibit: identical homes on this block</h2>"
            "<p class='note'>Every home below matches this property in ALL "
            "characteristics OPA records — area, lot, style, stories, year "
            "built, condition, quality, basement, garage, central air. "
            "Pennsylvania's uniformity clause makes assessment differences "
            "among comparables a recognized appeal ground.</p><table>"
            "<tr><th>Address</th><th class='num'>OPA market value</th></tr>"
        )
        for row in data.twins.to_dicts():
            hl = " class='hl'" if row["parcel_id"] == data.parcel_id else ""
            parts.append(
                f"<tr{hl}><td>{html.escape(str(row['address']))}"
                f"{' (this property)' if row['parcel_id'] == data.parcel_id else ''}</td>"
                f"<td class='num'>{_fmt_money(row['opa_market_value'])}</td></tr>"
            )
        median = data.twins["opa_market_value"].median()
        parts.append(
            f"<tr><th>Set median</th><th class='num'>{_fmt_money(median)}</th></tr></table>"
        )

    if data.comps is not None and data.comps.height:
        parts.append(
            "<h2>Comparable arms-length sales</h2>"
            "<p class='note'>Selected by model similarity (shared LightGBM leaf "
            "assignments); prices also shown adjusted to today via the district "
            "price index.</p><table><tr><th>Address</th><th>Sold</th>"
            "<th class='num'>Price</th><th class='num'>Adj. today</th>"
            "<th class='num'>Sqft</th><th>Style</th><th class='num'>Distance</th></tr>"
        )
        for r in data.comps.to_dicts():
            parts.append(
                f"<tr><td>{html.escape(str(r.get('address') or '?'))}</td>"
                f"<td>{r['sale_date']:%Y-%m-%d}</td>"
                f"<td class='num'>{_fmt_money(r.get('sale_price'))}</td>"
                f"<td class='num'>{_fmt_money(r.get('price_adj_today'))}</td>"
                f"<td class='num'>{_fmt(r.get('char_livable_area'))}</td>"
                f"<td>{_fmt(r.get('char_style'))}</td>"
                f"<td class='num'>{r.get('distance_m') or 0:,.0f}m</td></tr>"
            )
        parts.append("</table>")

    if data.assessment_history is not None and data.assessment_history.height >= 2:
        h = data.assessment_history
        first, last = h.row(0), h.row(-1)
        parts.append(
            "<h2>Assessment history</h2>"
            + _history_svg(h)
            + f"<p class='note'>{first[0]}: {_fmt_money(first[1])} → {last[0]}: "
            f"{_fmt_money(last[1])} ({(last[1] / first[1] - 1) * 100:+.0f}% over "
            f"{last[0] - first[0]} years)</p>"
        )

    if data.sale_history is not None and data.sale_history.height:
        parts.append(
            "<h2>Sale history (this parcel)</h2><table><tr><th>Date</th>"
            "<th class='num'>Price</th><th>Deed</th><th>Validity</th></tr>"
        )
        for r in data.sale_history.to_dicts():
            parts.append(
                f"<tr><td>{r['sale_date']:%Y-%m-%d}</td>"
                f"<td class='num'>{_fmt_money(r.get('sale_price'))}</td>"
                f"<td>{_fmt(r.get('deed_kind'))}</td>"
                f"<td>{_fmt(r.get('validity_status'))}</td></tr>"
            )
        parts.append("</table>")

    parts.append(
        "<h2>Provenance & caveats</h2><p class='note'>Screen built "
        f"{data.provenance.get('screen_built', '?')} from public city data "
        "(OPA roll, RTT deeds, L&amp;I records, PWD parcels, PASDA orthophotos). "
        "Characteristics are current-roll values, not as of past sale dates. "
        "This report is informational and is not legal or appraisal advice."
        "</p></body></html>"
    )
    return "".join(parts)


def build_property_report(
    query: str, data_dir: Path | None = None, out_dir: Path | None = None
) -> Path:
    from philly_assessments.models.comps import resolve_parcel

    root = data_dir if data_dir is not None else config.data_dir()
    candidates = resolve_parcel(query, data_dir)
    if not candidates:
        # the resolver only sees residential features; fall back to the screen
        screen = (
            pl.scan_parquet(root / "marts" / "assessment_screen.parquet")
            .filter(
                (pl.col("parcel_id") == query)
                | pl.col("address").str.to_uppercase().str.contains(
                    query.upper(), literal=True
                )
            )
            .select("parcel_id", "address")
            .head(5)
            .collect()
        )
        candidates = screen.to_dicts()
    if not candidates:
        raise KeyError(f"no property matches {query!r}")
    if len(candidates) > 1:
        options = "; ".join(f"{c['parcel_id']} {c['address']}" for c in candidates)
        raise KeyError(f"multiple matches for {query!r}: {options}")

    parcel_id = candidates[0]["parcel_id"]
    data = gather(parcel_id, data_dir)
    out_root = out_dir if out_dir is not None else root / "reports"
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"{parcel_id}.html"
    path.write_text(render_html(data))
    logger.info("report -> %s", path)
    return path
