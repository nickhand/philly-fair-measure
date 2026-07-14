"""Out-of-time audit for learned characteristic-conflict signals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from philly_fair_measure import config
from philly_fair_measure.models.metrics import evaluate_estimates
from philly_fair_measure.models.scoring import latest_run_dir


@dataclass(frozen=True)
class CharacteristicQualityAudit:
    baseline_run: Path
    segments: pl.DataFrame
    stress_properties: pl.DataFrame


def evaluate_quality_segments(predictions: pl.DataFrame, quality: pl.DataFrame) -> pl.DataFrame:
    joined = predictions.join(quality, on="parcel_id", how="left")
    segments = (
        ("all", pl.lit(True)),
        ("characteristic_outlier", pl.col("quality_characteristic_outlier").fill_null(False)),
        ("area_outlier", pl.col("quality_area_outlier").fill_null(False)),
        (
            "zero_bed_bath_conflict",
            pl.col("quality_zero_bed_bath_conflict").fill_null(False),
        ),
    )
    rows: list[dict[str, object]] = []
    for segment, expression in segments:
        frame = joined.filter(expression)
        rows.append(
            {
                "segment": segment,
                **evaluate_estimates(frame["pred_point"], frame["sale_price"]).as_row(),
            }
        )
    return pl.DataFrame(rows)


def characteristic_quality_check(
    data_dir: Path | None = None,
    *,
    baseline_run: Path | None = None,
) -> CharacteristicQualityAudit:
    root = data_dir if data_dir is not None else config.data_dir()
    run = baseline_run if baseline_run is not None else latest_run_dir("baseline", data_dir)
    quality_path = root / "marts" / "characteristic_quality.parquet"
    if not quality_path.exists():
        raise FileNotFoundError(
            f"{quality_path} missing; run `fair-measure build-characteristic-quality`"
        )
    predictions = pl.read_parquet(run / "predictions.parquet")
    quality = pl.read_parquet(quality_path)
    segments = evaluate_quality_segments(predictions, quality)

    stress_ids = ["371063501", "192222401"]
    stress = quality.filter(pl.col("parcel_id").is_in(stress_ids))
    feature_path = root / "marts" / "assessment_features.parquet"
    if feature_path.exists():
        observed_columns = [
            "parcel_id",
            "address",
            "char_livable_area",
            "char_beds",
            "char_baths",
            "char_area_conflict",
            "evt_n_active_change_occupancy_at_sale",
        ]
        feature_schema = pl.scan_parquet(feature_path).collect_schema().names()
        available = [column for column in observed_columns if column in feature_schema]
        stress = (
            pl.scan_parquet(feature_path)
            .select(available)
            .collect()
            .join(stress, on="parcel_id", how="right")
        )
    return CharacteristicQualityAudit(
        baseline_run=run,
        segments=segments,
        stress_properties=stress.sort("parcel_id"),
    )
