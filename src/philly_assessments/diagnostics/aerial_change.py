"""Aerial change-detection pilot: can free orthophotos see structural change?

PASDA publishes Philadelphia orthophoto vintages 1996-2025 as public ArcGIS
MapServers (live-verified 2026-07-03; ~15cm-class leaf-off imagery, tile
export works without keys). RENDER MATRIX (probed at 30/120/400m bboxes):
only the 2020, 2023, 2024, and 2025 services return pixels from /export —
2015-2019 and 2022 serve blank tiles at every scale (tile-cache shells).
Usable change pairs today: 2020-2023 (the pilot default), 2023-2024,
2023-2025. If per-parcel change scores separate parcels with KNOWN
structural change from quiet ones, the score earns a place as
assessment-screen evidence — the detector for work permits never saw
(the founding use case).

Pilot design (measure before scaling):
- ground truth positives: parcels with an L&I DEMOLITION completed between
  the flights (structure disappears — the strongest visual change) and
  parcels with a NEW CONSTRUCTION permit issued early in the window
- controls: parcels with no permits, demolitions, or unpermitted-work
  complaints anywhere near the window
- per parcel: fetch the same WGS84 bbox from both vintages (pixel-aligned by
  georeference), grayscale, quantile-match the later tile to the earlier one
  (kills illumination/film differences), then score change three ways:
  1 - SSIM over the tile, and 1 - Pearson r / mean abs diff over the
  parcel-polygon mask only
- report AUC per metric per group vs control; keep example image pairs on
  disk for eyeballing

Diagnostics only. Tiles and results live under data/diagnostics/aerial_pilot/.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from philly_assessments import catalog, config
from philly_assessments.scalars import as_float

if TYPE_CHECKING:
    import httpx
    from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)

PASDA_EXPORT = (
    "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/"
    "PhiladelphiaImagery{year}/MapServer/export"
)
TILE_PX = 256
MIN_BOX_M = 30.0  # rowhome parcels are ~5m wide; keep some context
PAD_FRAC = 0.15
_M_PER_DEG_LAT = 111_132.0


@dataclass(frozen=True)
class TilePair:
    parcel_id: str
    group: str
    early: np.ndarray  # grayscale float [0,1]
    late: np.ndarray
    mask: np.ndarray  # parcel-polygon pixels


def _square_bbox(geom: BaseGeometry) -> tuple[float, float, float, float]:
    """Square WGS84 bbox around the parcel with padding and a size floor."""
    lon0, lat0, lon1, lat1 = geom.bounds
    c_lon, c_lat = (lon0 + lon1) / 2, (lat0 + lat1) / 2
    m_per_deg_lon = _M_PER_DEG_LAT * np.cos(np.deg2rad(c_lat))
    w_m = max((lon1 - lon0) * m_per_deg_lon, (lat1 - lat0) * _M_PER_DEG_LAT)
    half_m = max(w_m * (1 + 2 * PAD_FRAC), MIN_BOX_M) / 2
    return (
        c_lon - half_m / m_per_deg_lon,
        c_lat - half_m / _M_PER_DEG_LAT,
        c_lon + half_m / m_per_deg_lon,
        c_lat + half_m / _M_PER_DEG_LAT,
    )


def fetch_tile(
    client: httpx.Client, year: int, bbox: tuple[float, float, float, float]
) -> np.ndarray | None:
    """One grayscale tile in [0,1], or None on failure/blank coverage."""
    from PIL import Image

    try:
        r = client.get(
            PASDA_EXPORT.format(year=year),
            params={
                "bbox": ",".join(f"{v:.7f}" for v in bbox),
                "bboxSR": 4326,
                "imageSR": 4326,
                "size": f"{TILE_PX},{TILE_PX}",
                "format": "png",
                "f": "image",
            },
        )
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
            return None
        img = np.asarray(Image.open(io.BytesIO(r.content)).convert("L"), dtype=np.float64)
    except Exception:  # noqa: BLE001 — pilot: any fetch/decode failure just drops the parcel
        return None
    img = img / 255.0
    if img.std() < 0.01:  # blank/no-coverage tile
        return None
    return img


def _quantile_match(late: np.ndarray, early: np.ndarray) -> np.ndarray:
    """Map the later tile's intensity distribution onto the earlier one's."""
    order = np.argsort(late, axis=None)
    matched = np.empty_like(late).reshape(-1)
    matched[order] = np.sort(early, axis=None)
    return matched.reshape(late.shape)


def _polygon_mask(geom: BaseGeometry, bbox: tuple[float, float, float, float]) -> np.ndarray:
    import shapely

    lon = np.linspace(bbox[0], bbox[2], TILE_PX)
    lat = np.linspace(bbox[3], bbox[1], TILE_PX)  # row 0 = north
    lon_g, lat_g = np.meshgrid(lon, lat)
    inside = shapely.contains_xy(geom, lon_g.ravel(), lat_g.ravel())
    return np.asarray(inside, dtype=bool).reshape(TILE_PX, TILE_PX)


_DS = 4  # downsample factor: ~15cm px -> ~60cm blocks (structure scale)


def _block_mean(img: np.ndarray, factor: int) -> np.ndarray:
    n = img.shape[0] // factor
    blocks = img[: n * factor, : n * factor].reshape(n, factor, n, factor).mean(axis=(1, 3))
    return np.asarray(blocks, dtype=np.float64)


def change_metrics(pair: TilePair) -> dict:
    from skimage.metrics import structural_similarity

    late = _quantile_match(pair.late, pair.early)

    def masked_scores(
        early: np.ndarray, late_m: np.ndarray, mask: np.ndarray
    ) -> tuple[float | None, float | None]:
        a, b = early[mask], late_m[mask]
        if len(a) >= 30 and a.std() > 0 and b.std() > 0:
            return float(1 - np.corrcoef(a, b)[0, 1]), float(np.abs(a - b).mean())
        return None, None

    ssim = structural_similarity(pair.early, late, data_range=1.0)
    corr, mad = masked_scores(pair.early, late, pair.mask)

    # structure scale: pixel-level noise (shadows, cars, ~px misregistration)
    # dominates 15cm comparisons; 60cm block means keep rooflines
    early_ds = _block_mean(pair.early, _DS)
    late_ds = _block_mean(late, _DS)
    mask_ds = _block_mean(pair.mask.astype(np.float64), _DS) > 0.5
    ssim_ds = structural_similarity(early_ds, late_ds, data_range=1.0)
    corr_ds, mad_ds = masked_scores(early_ds, late_ds, mask_ds)

    return {
        "parcel_id": pair.parcel_id,
        "group": pair.group,
        "score_ssim": float(1 - ssim),
        "score_corr": corr,
        "score_mad": mad,
        "score_ssim_ds": float(1 - ssim_ds),
        "score_corr_ds": corr_ds,
        "score_mad_ds": mad_ds,
        "mask_px": int(pair.mask.sum()),
    }


def build_pilot_sample(
    root: Path,
    *,
    vintage_early: int,
    vintage_late: int,
    n_demolition: int,
    n_construction: int,
    n_control: int,
    seed: int = 42,
) -> pl.DataFrame:
    """(parcel_id, group) rows with ground-truth labels between the flights.

    Events must fall strictly between the two spring flights, so the window
    runs from mid-year of the early vintage to end-of-year before the late
    one. Controls have no permits/demolitions/unpermitted-work complaints
    from two years before the early flight onward."""
    window_start = pl.datetime(vintage_early, 7, 1)
    window_stop = pl.datetime(vintage_late - 1, 12, 31)
    quiet_start = pl.datetime(vintage_early - 2, 1, 1)

    demos = (
        pl.scan_parquet(root / "staged" / "demolitions.parquet")
        .filter(
            pl.col("opa_account_num").is_not_null()
            & pl.coalesce("completed_date_parsed", "start_date_parsed").is_between(
                window_start, window_stop
            )
        )
        .select(pl.col("opa_account_num").alias("parcel_id"))
        .unique()
        .collect()
    )
    permits = pl.scan_parquet(root / "staged" / "permits.parquet")
    construction = (
        permits.filter(
            pl.col("opa_account_num").is_not_null()
            & (pl.col("typeofwork").cast(pl.String) == "New Construction")
            & pl.col("permitissuedate_parsed").is_between(
                window_start, pl.datetime(vintage_late - 2, 12, 31)
            )
        )
        .select(pl.col("opa_account_num").alias("parcel_id"))
        .unique()
        .collect()
    )
    touched = (
        pl.concat(
            [
                permits.filter(pl.col("permitissuedate_parsed") >= quiet_start).select(
                    pl.col("opa_account_num").alias("parcel_id")
                ),
                pl.scan_parquet(root / "staged" / "demolitions.parquet")
                .filter(pl.coalesce("completed_date_parsed", "start_date_parsed") >= quiet_start)
                .select(pl.col("opa_account_num").alias("parcel_id")),
                pl.scan_parquet(root / "staged" / "complaints.parquet")
                .filter(
                    (pl.col("complaintdate_parsed") >= quiet_start)
                    & pl.col("complaintcodename").cast(pl.String).str.contains("WORK UNDERWAY")
                )
                .select(pl.col("opa_account_num").alias("parcel_id")),
            ]
        )
        .unique()
        .collect()
    )
    residential = (
        pl.scan_parquet(root / "staged" / "opa_properties.parquet")
        .filter(pl.col("category_code_description").is_in(["SINGLE FAMILY", "MULTI FAMILY"]))
        .select(pl.col("parcel_number").alias("parcel_id"))
        .collect()
    )
    control = (
        residential.join(touched, on="parcel_id", how="anti")
        .sample(n=min(n_control * 3, residential.height), seed=seed)
        .head(n_control)
    )
    sample = pl.concat(
        [
            demos.sample(n=min(n_demolition, demos.height), seed=seed).with_columns(
                pl.lit("demolition").alias("group")
            ),
            construction.sample(n=min(n_construction, construction.height), seed=seed).with_columns(
                pl.lit("new_construction").alias("group")
            ),
            control.with_columns(pl.lit("control").alias("group")),
        ]
    )
    logger.info(
        "pilot sample: %s (demolition pool %s, construction pool %s)",
        sample.group_by("group").len().sort("group").to_dicts(),
        f"{demos.height:,}",
        f"{construction.height:,}",
    )
    return sample


def score_parcels(
    sample: pl.DataFrame,
    *,
    vintage_early: int,
    vintage_late: int,
    data_dir: Path | None = None,
    workers: int = 6,
    save_examples: int = 0,
    example_dir: Path | None = None,
) -> pl.DataFrame:
    """Fetch tile pairs and score change for a (parcel_id, group) frame.

    Parcels without PWD polygons, without coverage in either vintage, or with
    tiny masks are dropped (counts logged)."""
    import httpx
    import shapely
    from shapely import from_geojson

    pwd_ref = catalog.latest_snapshots(data_dir).get("pwd_parcels")
    if pwd_ref is None:
        raise FileNotFoundError("pwd_parcels snapshot missing")
    polys = (
        pl.scan_parquet(pwd_ref.data_path)
        .select(pl.col("brt_id").cast(pl.String).alias("parcel_id"), "geometry_geojson")
        .filter(pl.col("parcel_id").is_in(sample["parcel_id"].implode()))
        .collect()
        .unique(subset=["parcel_id"])
    )
    frame = sample.join(polys, on="parcel_id", how="inner")
    logger.info("%d of %d parcels have PWD polygons", frame.height, sample.height)

    geoms = from_geojson(frame["geometry_geojson"].to_numpy(), on_invalid="ignore")
    rows = frame.select("parcel_id", "group").to_dicts()

    results: list[dict] = []
    examples: list[tuple[str, str, np.ndarray, np.ndarray]] = []

    def process(ix: int) -> dict | None:
        geom = geoms[ix]
        if geom is None or geom.is_empty or not shapely.is_valid(geom):
            return None
        bbox = _square_bbox(geom)
        with httpx.Client(timeout=60) as client:
            early = fetch_tile(client, vintage_early, bbox)
            late = fetch_tile(client, vintage_late, bbox)
        if early is None or late is None:
            return None
        mask = _polygon_mask(geom, bbox)
        if mask.sum() < 30:
            return None
        pair = TilePair(rows[ix]["parcel_id"], rows[ix]["group"], early, late, mask)
        metrics = change_metrics(pair)
        if len(examples) < save_examples and rows[ix]["group"] != "control":
            examples.append((pair.parcel_id, pair.group, early, late))
        return metrics

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for out in pool.map(process, range(len(rows))):
            if out is not None:
                results.append(out)
    logger.info("scored %d of %d parcels", len(results), len(rows))

    if examples and example_dir is not None:
        example_dir.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        for parcel_id, group, early, late in examples:
            side = np.concatenate([early, np.ones((TILE_PX, 4)), late], axis=1)
            Image.fromarray((side * 255).astype(np.uint8)).save(
                example_dir / f"{group}_{parcel_id}_{vintage_early}_vs_{vintage_late}.png"
            )
    return pl.DataFrame(results)


def run_aerial_pilot(
    data_dir: Path | None = None,
    *,
    vintage_early: int = 2020,
    vintage_late: int = 2023,
    n_demolition: int = 200,
    n_construction: int = 200,
    n_control: int = 300,
    workers: int = 6,
    save_examples: int = 6,
) -> pl.DataFrame:
    from philly_assessments.ingest.derived import write_derived_table

    root = data_dir if data_dir is not None else config.data_dir()
    sample = build_pilot_sample(
        root,
        vintage_early=vintage_early,
        vintage_late=vintage_late,
        n_demolition=n_demolition,
        n_construction=n_construction,
        n_control=n_control,
    )
    table = score_parcels(
        sample,
        vintage_early=vintage_early,
        vintage_late=vintage_late,
        data_dir=data_dir,
        workers=workers,
        save_examples=save_examples,
        example_dir=root / "diagnostics" / "aerial_pilot_examples",
    )
    write_derived_table(
        table,
        root,
        "diagnostics",
        "aerial_pilot",
        [],
        notes=f"vintages {vintage_early} vs {vintage_late}; PASDA MapServer tiles",
    )

    return table


def run_aerial_score(
    data_dir: Path | None = None,
    *,
    vintage_early: int = 2023,
    vintage_late: int = 2025,
    flags: tuple[str, ...] = ("over_assessed_candidate", "under_assessed_candidate"),
    n_control: int = 300,
    workers: int = 6,
    limit: int | None = None,
) -> pl.DataFrame:
    """Score the assessment screen's flagged residential parcels for aerial
    change and persist screen-joinable evidence.

    A fresh quiet-control sample is scored alongside the targets so the
    change threshold is calibrated for THIS vintage pair (flight gap and
    imaging conditions shift the whole score distribution): a parcel is
    change-flagged when its score exceeds the controls' 90th percentile —
    the pilot's 10% false-positive budget, at which ~42% of known structural
    change was caught."""
    from philly_assessments.ingest.derived import write_derived_table

    root = data_dir if data_dir is not None else config.data_dir()
    screen_path = root / "marts" / "assessment_screen.parquet"
    if not screen_path.exists():
        raise FileNotFoundError(f"{screen_path} missing; run `philly screen-assessments` first")
    screen = pl.scan_parquet(screen_path)
    if "model_family" in screen.collect_schema().names():
        screen = screen.filter(pl.col("model_family") == "residential")
    targets = (
        screen.filter(pl.col("assessment_flag").is_in(list(flags)))
        .select("parcel_id")
        .unique()
        .collect()
        .with_columns(pl.lit("screen_flagged").alias("group"))
    )
    if limit is not None:
        targets = targets.head(limit)
    controls = build_pilot_sample(
        root,
        vintage_early=vintage_early,
        vintage_late=vintage_late,
        n_demolition=0,
        n_construction=0,
        n_control=n_control,
    ).filter(pl.col("group") == "control")
    logger.info("aerial-score: %d flagged parcels + %d controls", targets.height, controls.height)

    table = score_parcels(
        pl.concat([targets, controls]),
        vintage_early=vintage_early,
        vintage_late=vintage_late,
        data_dir=data_dir,
        workers=workers,
    )
    threshold = as_float(
        table.filter(pl.col("group") == "control")["score_corr"].drop_nulls().quantile(0.9)
    )
    pair = f"{vintage_early}_vs_{vintage_late}"
    scores = (
        table.filter(pl.col("group") == "screen_flagged")
        .select(
            "parcel_id",
            pl.col("score_corr").alias("aerial_change_score"),
            (pl.col("score_corr") > threshold).alias("aerial_change_flag"),
            pl.lit(pair).alias("aerial_pair"),
        )
        .drop_nulls("aerial_change_score")
    )
    write_derived_table(
        scores,
        root,
        "diagnostics",
        "aerial_change_scores",
        [],
        notes=f"pair {pair}; control-calibrated threshold {threshold:.4f} "
        f"(90th pct of {n_control} quiet parcels)",
    )
    logger.info(
        "aerial change scores: %d parcels, threshold %.3f, %d flagged",
        scores.height,
        threshold,
        int(scores["aerial_change_flag"].sum()),
    )
    return scores


def pilot_summary(table: pl.DataFrame) -> pl.DataFrame:
    """AUC of each change score for each event group vs control."""
    from sklearn.metrics import roc_auc_score

    rows = []
    control = table.filter(pl.col("group") == "control")
    metrics = [c for c in table.columns if c.startswith("score_")]
    for group in ("demolition", "new_construction"):
        event = table.filter(pl.col("group") == group)
        for metric in metrics:
            sub = pl.concat([event, control]).drop_nulls(metric)
            if sub["group"].n_unique() < 2:
                continue
            auc = roc_auc_score((sub["group"] == group).to_numpy(), sub[metric].to_numpy())
            rows.append(
                {
                    "group": group,
                    "metric": metric,
                    "n_event": event.drop_nulls(metric).height,
                    "n_control": control.drop_nulls(metric).height,
                    "auc_vs_control": float(auc),
                    "median_event": as_float(event[metric].drop_nulls().median()),
                    "median_control": as_float(control[metric].drop_nulls().median()),
                }
            )
    return pl.DataFrame(rows)
