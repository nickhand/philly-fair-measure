"""Public dashboard API: the JSON layer the web front door reads.

Serves the assessment screen and the per-property analysis (drivers, equity,
history) to `web/`. Design notes:

- The screen mart plus coordinates is loaded ONCE at startup into an in-memory
  polars frame (~500k rows) — search, map bbox queries, and property cores are
  all sub-millisecond scans of that frame.
- The heavy per-property endpoints (`/report`, `/comps`) recompute on request
  from the marts and model artifacts; ~1s each today because the booster is
  reloaded per call (fine for a single-host public tool; memoize before real
  traffic).
- Admin endpoints are NOT authenticated — they are for local/staff use and the
  deploy story must add real auth before exposure (documented in
  docs/frontend.md).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from philly_fair_measure import config
from philly_fair_measure.ingest.manifests import read_derived_manifest
from philly_fair_measure.vocab import AssessmentFlag, RunKind

logger = logging.getLogger(__name__)

_SEARCH_LIMIT = 10
_BBOX_LIMIT = 4000
_HIST_BINS = 24
_HIST_LO, _HIST_HI = 0.4, 1.6
_VALUE_BAND = 1.5  # mirrors equity_context peer rule
_MIN_VALUE = 30_000.0


def _f(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _i(value: object) -> int | None:
    f = _f(value)
    return None if f is None else int(f)


# ---------------------------------------------------------------- responses


class SearchHit(BaseModel):
    parcel_id: str
    address: str
    opa_market_value: float | None


class Signals(BaseModel):
    """Neutral 'what we see in city data' chips for the property page."""

    aerial_change: bool
    aerial_pair: str | None
    vacancy_complaints_5y: int | None
    unpermitted_work_complaints_5y: int | None
    tax_delinquent: bool
    owner_occupied: bool
    linked_parcels: int | None


class PropertyCore(BaseModel):
    parcel_id: str
    address: str
    category: str | None
    model_family: str | None
    interval_method: str | None
    opa_market_value: float | None
    model_median: float | None
    model_pi_low_90: float | None
    model_pi_high_90: float | None
    # the range both uncertainty machines support (Bayesian ∩ conformal for
    # residential; the native band elsewhere) — what surfaces should display.
    # Flags are still judged against model_pi_*.
    display_pi_low_90: float | None = None
    display_pi_high_90: float | None = None
    ratio: float | None
    screen_z: float | None
    flag: str
    # within-range but at/beyond the outer tenth of the DISPLAYED band
    # ("high"/"low") — weaker evidence than a flag, "worth a closer look"
    attention: str | None = None
    # built within ~a year of the valuation date: comp evidence runs low on
    # new construction, so the report shows a caveat
    new_build: bool = False
    twin_n: int | None
    twin_ratio: float | None
    lon: float | None
    lat: float | None
    signals: Signals


class DriverOut(BaseModel):
    label: str
    group: str
    value: str | None
    dollars: float


class GroupEffect(BaseModel):
    group: str
    dollars: float


class AppealFact(BaseModel):
    label: str
    recorded: str
    dollars: float
    implausible: bool
    # the city has no value on file; the model used a typical value instead,
    # and that substitution is what the dollar effect reflects
    missing: bool = False


class Drivers(BaseModel):
    base_value: float
    value: float
    drivers: list[DriverOut]
    groups: list[GroupEffect]
    sentences: list[str]
    appeal_facts: list[AppealFact]


class HistBin(BaseModel):
    x0: float
    x1: float
    n: int


class Equity(BaseModel):
    ratio: float
    peer_median_ratio: float
    peer_n: int
    percentile: float
    peer_label: str
    verdict: str
    histogram: list[HistBin]


class YearValue(BaseModel):
    year: int
    value: float


class SaleRow(BaseModel):
    date: str
    price: float | None
    deed_kind: str | None
    validity: str | None


class Report(BaseModel):
    drivers: Drivers | None
    equity: Equity | None
    assessment_history: list[YearValue]
    sale_history: list[SaleRow]
    screen_built: str | None


class CompRow(BaseModel):
    address: str
    sale_date: str
    sale_price: float | None
    price_adj_today: float | None
    livable_area: float | None
    distance_m: float | None
    # shared-LightGBM-leaf similarity in [0, 1] (models/comps.py); null for
    # condo building comps, which are selected by building membership instead
    similarity: float | None = None


class Stats(BaseModel):
    properties: int
    within: int
    over: int
    under: int
    # within-range homes at/beyond the displayed band's edge (attention
    # tier) — the "worth a closer look" count, weaker evidence than over/under
    watch: int
    median_ratio: float | None
    screen_built: str | None


class LeaderRow(BaseModel):
    parcel_id: str
    address: str
    opa_market_value: float | None
    model_median: float | None
    ratio: float | None
    screen_z: float | None
    twin_n: int | None
    twin_ratio: float | None


# ---------------------------------------------------------------- app state


def _load_frame(root: Path) -> tuple[pl.DataFrame, str | None]:
    """Screen mart joined with coordinates/zip from the feature marts."""
    screen_path = root / "marts" / "assessment_screen.parquet"
    screen = pl.read_parquet(screen_path)
    coord_parts = []
    for name in ("assessment_features", "condo_assessment_features"):
        path = root / "marts" / f"{name}.parquet"
        if path.exists():
            coord_parts.append(
                pl.scan_parquet(path)
                .select("parcel_id", "loc_lon", "loc_lat", "loc_zip5")
                .collect()
            )
    if coord_parts:
        coords = pl.concat(coord_parts).unique(subset="parcel_id", keep="first")
        screen = screen.join(coords, on="parcel_id", how="left")
    else:  # tolerate coordinate-less test fixtures
        screen = screen.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("loc_lon"),
            pl.lit(None, dtype=pl.Float64).alias("loc_lat"),
            pl.lit(None, dtype=pl.Utf8).alias("loc_zip5"),
        )
    built: str | None
    try:
        built = read_derived_manifest(screen_path).built_at.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 — provenance is optional in fixtures
        built = None
    logger.info("api loaded %s screen rows", f"{screen.height:,}")
    return screen, built


def _row(frame: pl.DataFrame, parcel_id: str) -> dict[str, Any]:
    hit = frame.filter(pl.col("parcel_id") == parcel_id)
    if not hit.height:
        raise HTTPException(status_code=404, detail=f"parcel {parcel_id} not found")
    return hit.to_dicts()[0]


def _core(s: dict[str, Any]) -> PropertyCore:
    return PropertyCore(
        parcel_id=str(s["parcel_id"]),
        address=str(s.get("address") or ""),
        category=s.get("char_category"),
        model_family=s.get("model_family"),
        interval_method=s.get("interval_method"),
        opa_market_value=_f(s.get("opa_market_value")),
        # the headline estimate is display_median (Stage 5: the calibrated
        # stacked point — drivers explain it via blended SHAP); model_*
        # stays the Bayesian gate machine, served for the methods footnote
        model_median=_f(
            s.get("display_median")
            if s.get("display_median") is not None
            else s.get("model_median")
        ),
        model_pi_low_90=_f(s.get("model_pi_low_90")),
        model_pi_high_90=_f(s.get("model_pi_high_90")),
        display_pi_low_90=_f(
            s.get("display_pi_low_90")
            if s.get("display_pi_low_90") is not None
            else s.get("model_pi_low_90")
        ),
        display_pi_high_90=_f(
            s.get("display_pi_high_90")
            if s.get("display_pi_high_90") is not None
            else s.get("model_pi_high_90")
        ),
        ratio=_f(
            s.get("display_ratio")
            if s.get("display_ratio") is not None
            else s.get("opa_vs_model_ratio")
        ),
        screen_z=_f(s.get("screen_z")),
        flag=str(s.get("assessment_flag") or AssessmentFlag.NONE),
        attention=s.get("attention"),
        new_build=bool(s.get("new_build")),
        twin_n=_i(s.get("twin_n")),
        twin_ratio=_f(s.get("opa_vs_twin_median")),
        lon=_f(s.get("loc_lon")),
        lat=_f(s.get("loc_lat")),
        signals=Signals(
            aerial_change=bool(s.get("aerial_change_flag")),
            aerial_pair=s.get("aerial_pair"),
            vacancy_complaints_5y=_i(s.get("evt_n_vacant_complaints_5y_before")),
            unpermitted_work_complaints_5y=_i(s.get("evt_n_unpermitted_work_complaints_5y_before")),
            tax_delinquent=bool(_f(s.get("dist_tax_delinquent")) or 0.0),
            owner_occupied=bool(_f(s.get("ten_owner_occupied_at_sale")) or 0.0),
            linked_parcels=_i(s.get("shp_n_linked_parcels")),
        ),
    )


def _peer_histogram(frame: pl.DataFrame, s: dict[str, Any]) -> list[HistBin]:
    """Ratio distribution of the SAME peer set the equity statistics use
    (equity_context.peer_predicate — family, ZIP, never the subject or, for
    condos, its own building), so the chart and the sentence below it can
    never describe different populations."""
    from philly_fair_measure.equity_context import _MIN_PEERS, peer_predicate

    zip5, median = s.get("loc_zip5"), _f(s.get("display_median") or s.get("model_median"))
    if not zip5 or not median:
        return []
    family = str(s.get("model_family") or "residential")
    frame = frame.filter(peer_predicate(family, s.get("parcel_id"), zip5, s.get("building_id")))
    # choose the population exactly the way equity_context does (value band,
    # falling back to the whole neighborhood below the SAME threshold), then
    # clip only for the fixed chart axes — so the chart and the sentence can
    # never describe different peer sets
    band = frame.filter(
        pl.col("display_median").is_between(median / _VALUE_BAND, median * _VALUE_BAND)
    )
    pool = band if band.height >= _MIN_PEERS else frame
    peers = pool.filter(pl.col("display_ratio").is_between(_HIST_LO, _HIST_HI))
    if not peers.height:
        return []
    ratios = peers["display_ratio"].to_numpy()
    width = (_HIST_HI - _HIST_LO) / _HIST_BINS
    bins: list[HistBin] = []
    for b in range(_HIST_BINS):
        x0 = _HIST_LO + b * width
        x1 = x0 + width
        n = int(((ratios >= x0) & (ratios < x1)).sum())
        bins.append(HistBin(x0=round(x0, 3), x1=round(x1, 3), n=n))
    return bins


def _drivers(root: Path, parcel_id: str, s: dict[str, Any]) -> Drivers | None:
    from philly_fair_measure.models.explain import (
        appeal_points,
        decode_recorded,
        display_value,
        explain,
        plain_language,
    )
    from philly_fair_measure.models.scoring import latest_run_dir

    # Both families share the explain layer: the condo run persists the same
    # artifacts (booster, feature lists, categorical mappings) as the baseline.
    is_condo = s.get("model_family") == "condo"
    mart = "condo_assessment_features.parquet" if is_condo else "assessment_features.parquet"
    run_kind: RunKind = "condo" if is_condo else "baseline"
    feat = pl.scan_parquet(root / "marts" / mart).filter(pl.col("parcel_id") == parcel_id).collect()
    if not feat.height:
        return None
    exp = explain(latest_run_dir(run_kind, root), feat)[0]
    headline = _f(s.get("display_median") or s.get("model_median"))
    if headline and headline > 0:
        exp = exp.anchored_to(headline)
    characteristics = feat.to_dicts()[0]
    top = sorted(exp.drivers, key=lambda d: -abs(d.dollar_effect))[:8]
    return Drivers(
        base_value=exp.base_value,
        value=exp.value,
        drivers=[
            DriverOut(
                label=d.label,
                group=d.group,
                value=display_value(d.feature, d.raw_value),
                dollars=round(d.dollar_effect),
            )
            for d in top
        ],
        groups=[GroupEffect(group=g, dollars=round(v)) for g, v in exp.by_group()],
        sentences=plain_language(exp, n=5),
        appeal_facts=[
            AppealFact(
                label=p.label,
                recorded=decode_recorded(p.feature, p.recorded_value)
                or display_value(p.feature, p.recorded_value)
                or ("Not on file" if p.recorded_value is None else str(p.recorded_value)),
                dollars=round(p.dollar_effect),
                implausible=p.implausible,
                missing=p.recorded_value is None,
            )
            for p in appeal_points(exp, characteristics)
        ],
    )


def _equity(frame: pl.DataFrame, root: Path, s: dict[str, Any]) -> Equity | None:
    from philly_fair_measure.equity_context import equity_context

    ctx = equity_context(s, root)
    if ctx is None:
        return None
    return Equity(
        ratio=ctx.ratio,
        peer_median_ratio=ctx.peer_median_ratio,
        peer_n=ctx.peer_n,
        percentile=ctx.percentile,
        peer_label=ctx.peer_label,
        verdict=ctx.verdict,
        histogram=_peer_histogram(frame, s),
    )


def _condo_building_comps(
    root: Path, frame: pl.DataFrame, s: dict[str, Any], k: int = 8
) -> list[CompRow]:
    """Recent arms-length sales in the subject's own building — the condo
    equivalent of comps (same location and building; the size column lets the
    reader scale between units). distance_m=0 renders as "same building"."""
    building = s.get("building_id")
    mart = root / "marts" / "condo_sale_features.parquet"
    if building is None or not mart.exists():
        return []
    sales = (
        pl.scan_parquet(mart)
        .filter((pl.col("building_id") == building) & (pl.col("parcel_id") != s.get("parcel_id")))
        .select("parcel_id", "sale_date", "sale_price", "char_unit_area", "time_adj_log")
        .sort("sale_date", descending=True)
        .head(k)
        .collect()
    )
    if not sales.height:
        return []
    addresses = dict(
        frame.filter(pl.col("parcel_id").is_in(sales["parcel_id"].to_list()))
        .select("parcel_id", "address")
        .iter_rows()
    )
    return [
        CompRow(
            address=str(addresses.get(str(r["parcel_id"]), r["parcel_id"])),
            sale_date=str(r["sale_date"])[:10],
            sale_price=_f(r["sale_price"]),
            # sale-date dollars moved to the index reference (~today), the
            # same convention as the residential comps' price_adj_today
            price_adj_today=(
                float(r["sale_price"]) * math.exp(float(r["time_adj_log"] or 0.0))
                if r["sale_price"] is not None
                else None
            ),
            livable_area=_f(r["char_unit_area"]),
            distance_m=0.0,
        )
        for r in sales.to_dicts()
    ]


def _histories(root: Path, parcel_id: str) -> tuple[list[YearValue], list[SaleRow]]:
    assessments: list[YearValue] = []
    path = root / "staged" / "assessments.parquet"
    if path.exists():
        rows = (
            pl.scan_parquet(path)
            .filter(
                (pl.col("parcel_number") == parcel_id)
                & pl.col("year_parsed").is_not_null()
                & (pl.col("market_value").fill_null(0) > 0)
            )
            .select(pl.col("year_parsed").alias("year"), "market_value")
            .sort("year")
            .collect()
        )
        assessments = [
            YearValue(year=int(r["year"]), value=float(r["market_value"])) for r in rows.to_dicts()
        ]
    sales: list[SaleRow] = []
    path = root / "marts" / "sale_validity.parquet"
    if path.exists():
        rows = (
            pl.scan_parquet(path)
            .filter((pl.col("parcel_id") == parcel_id) & pl.col("sale_date").is_not_null())
            .select("sale_date", "sale_price", "deed_kind", "validity_status")
            .sort("sale_date", descending=True)
            .head(10)
            .collect()
        )
        sales = [
            SaleRow(
                date=str(r["sale_date"])[:10],
                price=_f(r["sale_price"]),
                deed_kind=r["deed_kind"],
                validity=r["validity_status"],
            )
            for r in rows.to_dicts()
        ]
    return assessments, sales


# ---------------------------------------------------------------- factory


def create_app(data_dir: Path | None = None) -> FastAPI:
    import os

    from fastapi import Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.responses import JSONResponse

    root = data_dir if data_dir is not None else config.data_dir()
    frame, screen_built = _load_frame(root)
    app = FastAPI(title="Philly Assessment Check API", docs_url="/api/docs")
    # the citywide overview payload is ~51k GeoJSON points (~6 MB raw, ~10x
    # smaller gzipped); everything else compresses as a free bonus
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Unhandled exceptions must become a response HERE, inside CORSMiddleware
    # (added below, so it wraps this) — a 500 escaping to the outer stack
    # carries no CORS headers, and the browser then reports an opaque
    # "access control" failure instead of the real status.
    @app.middleware("http")
    async def json_500(request: Request, call_next: Any) -> Response:
        try:
            return await call_next(request)  # type: ignore[no-any-return]
        except Exception:
            logger.exception("unhandled error on %s", request.url.path)
            return JSONResponse({"detail": "internal server error"}, status_code=500)

    # public read-only data service: the site is served from another origin
    # (Netlify / nickhand.dev) and calls the Fly API directly. GET-only, no
    # credentials, so a permissive default is appropriate; override with a
    # comma-separated PHILLY_CORS_ORIGINS if it ever needs narrowing.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in os.environ.get("PHILLY_CORS_ORIGINS", "*").split(",")],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def _require_admin(x_admin_token: str | None) -> None:
        """Admin endpoints are staff worklists. Locally (no PHILLY_ENV) they
        stay open; in prod they require the PHILLY_ADMIN_TOKEN header and are
        denied outright if no token was configured."""
        token = os.environ.get("PHILLY_ADMIN_TOKEN")
        if token:
            if x_admin_token != token:
                raise HTTPException(status_code=403, detail="admin token required")
        elif os.environ.get("PHILLY_ENV") == "prod":
            raise HTTPException(status_code=404, detail="not found")

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Fly.io health checks (cheap: the frame loaded at startup)."""
        return {"status": "ok", "rows": frame.height, "screen_built": screen_built}

    @app.get("/api/stats", response_model=Stats)
    def stats() -> Stats:
        flags = frame["assessment_flag"]
        return Stats(
            properties=frame.height,
            within=int((flags == AssessmentFlag.WITHIN).sum()),
            over=int((flags == AssessmentFlag.OVER).sum()),
            under=int((flags == AssessmentFlag.UNDER).sum()),
            watch=int(frame["attention"].is_not_null().sum()),
            median_ratio=_f(frame["display_ratio"].median()),
            screen_built=screen_built,
        )

    @app.get("/api/search", response_model=list[SearchHit])
    def search(q: str = Query(min_length=2, max_length=80)) -> list[SearchHit]:
        needle = q.strip().upper()
        hits = (
            frame.filter(
                pl.col("address").str.contains(needle, literal=True)
                | (pl.col("parcel_id") == needle)
            )
            .with_columns(pl.col("address").str.starts_with(needle).alias("_pref"))
            .sort(["_pref", "address"], descending=[True, False])
            .head(_SEARCH_LIMIT)
        )
        return [
            SearchHit(
                parcel_id=str(r["parcel_id"]),
                address=str(r["address"]),
                opa_market_value=_f(r["opa_market_value"]),
            )
            for r in hits.to_dicts()
        ]

    @app.get("/api/parcels")
    def parcels(
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        limit: int = Query(default=_BBOX_LIMIT, le=_BBOX_LIMIT),
    ) -> dict[str, Any]:
        """GeoJSON points in a map viewport (client gates to high zoom)."""
        sub = frame.filter(
            pl.col("loc_lon").is_between(minx, maxx) & pl.col("loc_lat").is_between(miny, maxy)
        ).head(limit)
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["loc_lon"], r["loc_lat"]]},
                "properties": {
                    "id": r["parcel_id"],
                    # address rides along so stacked dots (condo towers share
                    # one coordinate) can offer a pick-a-home list on click
                    "address": r["address"],
                    "flag": r["assessment_flag"],
                    "attention": r["attention"],
                    "opa": r["opa_market_value"],
                    "model": r["display_median"],
                    "family": r["model_family"],
                },
            }
            for r in sub.select(
                "parcel_id",
                "address",
                "loc_lon",
                "loc_lat",
                "assessment_flag",
                "attention",
                "opa_market_value",
                "display_median",
                "model_family",
            ).to_dicts()
            if r["loc_lon"] is not None
        ]
        return {"type": "FeatureCollection", "features": features}

    flagged_cache: dict[str, Any] = {}

    @app.get("/api/parcels/flagged")
    def parcels_flagged() -> dict[str, Any]:
        """The citywide overview payload: every flagged (over/under) home plus
        the watch tier (within range, near its edge) — ~51k points, shipped
        whole (gzipped ~10x) so the map can show the pattern at low zoom.
        Built once and cached; coordinates rounded to ~1 m so the comfortable
        within-range half-million stays the only viewport-gated data."""
        if not flagged_cache:
            sub = frame.filter(
                (
                    pl.col("assessment_flag").is_in(
                        [str(AssessmentFlag.OVER), str(AssessmentFlag.UNDER)]
                    )
                    | pl.col("attention").is_not_null()
                )
                & pl.col("loc_lon").is_not_null()
            )
            flagged_cache["fc"] = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [round(r["loc_lon"], 5), round(r["loc_lat"], 5)],
                        },
                        "properties": {
                            "id": r["parcel_id"],
                            "address": r["address"],
                            "flag": r["assessment_flag"],
                            "attention": r["attention"],
                            "opa": r["opa_market_value"],
                            # condo flags come from the condo-unit model and
                            # cluster in towers; the map lets users separate them
                            "family": r["model_family"],
                        },
                    }
                    for r in sub.select(
                        "parcel_id",
                        "address",
                        "loc_lon",
                        "loc_lat",
                        "assessment_flag",
                        "attention",
                        "opa_market_value",
                        "model_family",
                    ).to_dicts()
                ],
            }
        return flagged_cache["fc"]  # type: ignore[no-any-return]

    @app.get("/api/property/{parcel_id}", response_model=PropertyCore)
    def property_core(parcel_id: str) -> PropertyCore:
        return _core(_row(frame, parcel_id))

    @app.get("/api/property/{parcel_id}/report", response_model=Report)
    def property_report(parcel_id: str) -> Report:
        s = _row(frame, parcel_id)
        drivers: Drivers | None = None
        equity: Equity | None = None
        try:
            drivers = _drivers(root, parcel_id, s)
        except Exception:  # noqa: BLE001 — driver panel is optional evidence
            logger.warning("drivers unavailable for %s", parcel_id, exc_info=True)
        try:
            equity = _equity(frame, root, s)
        except Exception:  # noqa: BLE001 — equity panel is optional evidence
            logger.warning("equity unavailable for %s", parcel_id, exc_info=True)
        assessments, sales = _histories(root, parcel_id)
        return Report(
            drivers=drivers,
            equity=equity,
            assessment_history=assessments,
            sale_history=sales,
            screen_built=screen_built,
        )

    @app.get("/api/property/{parcel_id}/comps", response_model=list[CompRow])
    def property_comps(parcel_id: str) -> list[CompRow]:
        from philly_fair_measure.models.comps import find_comps

        row = _row(frame, parcel_id)  # 404 before the slow path
        if row.get("model_family") == "condo":
            # the leaf-comp machinery is residential-only; a condo's natural
            # comps are recent arms-length sales in its own building
            return _condo_building_comps(root, frame, row)
        try:
            comps = find_comps(parcel_id, root, k=8).comps
        except Exception as err:  # noqa: BLE001 — comps need model artifacts
            raise HTTPException(status_code=503, detail="comps unavailable") from err
        return [
            CompRow(
                address=str(r.get("address") or ""),
                sale_date=str(r.get("sale_date"))[:10],
                sale_price=_f(r.get("sale_price")),
                price_adj_today=_f(r.get("price_adj_today")),
                livable_area=_f(r.get("char_livable_area")),
                distance_m=_f(r.get("distance_m")),
                similarity=_f(r.get("similarity")),
            )
            for r in comps.to_dicts()
        ]

    @app.get("/api/admin/leaderboard", response_model=list[LeaderRow])
    def admin_leaderboard(
        kind: str = Query(pattern="^(over|under|nonuniform)$"),
        n: int = Query(default=25, le=100),
        extremes: bool = False,
        x_admin_token: str | None = Header(default=None),
    ) -> list[LeaderRow]:
        """Staff worklists. Open locally; in prod requires X-Admin-Token
        (PHILLY_ADMIN_TOKEN secret) and 404s if no token is configured."""
        _require_admin(x_admin_token)
        from philly_fair_measure.report import leaderboards

        boards = leaderboards(root, n=n, plausible=not extremes)
        key = {
            "over": "over_assessed",
            "under": "under_assessed",
            "nonuniform": "non_uniform_block",
        }[kind]
        return [
            LeaderRow(
                parcel_id=str(r["parcel_id"]),
                address=str(r["address"]),
                opa_market_value=_f(r.get("opa_market_value")),
                model_median=_f(r.get("display_median") or r.get("model_median")),
                ratio=_f(r.get("display_ratio") or r.get("opa_vs_model_ratio")),
                screen_z=_f(r.get("screen_z")),
                twin_n=_i(r.get("twin_n")),
                twin_ratio=_f(r.get("opa_vs_twin_median")),
            )
            for r in boards[key].to_dicts()
        ]

    return app
