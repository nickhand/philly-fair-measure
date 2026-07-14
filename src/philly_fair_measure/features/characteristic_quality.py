"""Cross-fitted plausibility models for current property characteristics.

OPA characteristics are measurements, not ground truth.  This module learns
the joint pattern of internally coherent residential records and reconstructs
three especially consequential fields -- living area, bedrooms, and bathrooms
-- from independent structure, type, and location evidence.  Every published
prediction is out-of-fold by parcel, and neither sale price nor assessment
value is an input.

The output is deliberately diagnostic.  Expected living area is a peer-model
prior, not a replacement for OPA living area or footprint-derived gross area.
Valuation models may consume these columns only after an out-of-time ablation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import polars as pl

from philly_fair_measure import config
from philly_fair_measure.features.sale_features import (
    _CHAR_RENAMES,
    _LOC_RENAMES,
    era_expr,
    style_expr,
)
from philly_fair_measure.features.structure import add_building_structure_features
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import DerivedManifest, InputRef, read_derived_manifest
from philly_fair_measure.models.baseline import RESIDENTIAL_CATEGORIES

logger = logging.getLogger(__name__)

MODEL_VERSION: Final = 1
DEFAULT_FOLDS: Final = 3
DEFAULT_SEED: Final = 42

NUMERIC_PREDICTORS: Final = (
    "char_lot_area",
    "char_frontage",
    "char_depth",
    "char_stories",
    "char_year_built",
    "char_footprint_sqft",
    "char_footprint_estimated_floors",
    "char_footprint_gross_sqft",
    "char_footprint_story_gap",
    "loc_lon",
    "loc_lat",
)

CATEGORICAL_PREDICTORS: Final = (
    "char_category",
    "char_building_type",
    "char_style",
    "char_era",
    "char_exterior_condition",
    "char_interior_condition",
    "loc_zip5",
    "loc_ward",
)

QUALITY_COLUMNS: Final = (
    "quality_expected_livable_area",
    "quality_area_reference_low_90",
    "quality_area_reference_high_90",
    "quality_area_ratio_to_expected",
    "quality_area_log_residual",
    "quality_area_disagreement_z",
    "quality_area_outlier",
    "quality_expected_beds",
    "quality_expected_baths",
    "quality_bed_zero_conflict",
    "quality_bath_zero_conflict",
    "quality_zero_bed_bath_conflict",
    "quality_characteristic_conflict_score",
    "quality_characteristic_outlier",
)

_AREA_MIN = 300.0
_AREA_MAX = 10_000.0
_COHERENT_RATIO_LOW = 0.55
_COHERENT_RATIO_HIGH = 1.30
_AREA_OUTLIER_QUANTILE = 0.995


@dataclass(frozen=True)
class CharacteristicQualityResult:
    frame: pl.DataFrame
    metadata: dict[str, object]


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: DerivedManifest
    metadata_path: Path


def _ensure_columns(frame: pl.DataFrame) -> pl.DataFrame:
    expressions: list[pl.Expr] = []
    for column in NUMERIC_PREDICTORS:
        if column not in frame.columns:
            expressions.append(pl.lit(None, dtype=pl.Float64).alias(column))
    for column in CATEGORICAL_PREDICTORS:
        if column not in frame.columns:
            expressions.append(pl.lit(None, dtype=pl.String).alias(column))
    for column in (
        "char_livable_area",
        "char_beds",
        "char_baths",
        "char_livable_to_footprint_gross_ratio",
        "char_area_conflict",
    ):
        if column not in frame.columns:
            expressions.append(pl.lit(None, dtype=pl.Float64).alias(column))
    return frame.with_columns(*expressions) if expressions else frame


def _matrix(
    frame: pl.DataFrame,
) -> tuple[npt.NDArray[np.float64], list[int]]:
    numeric = frame.select(
        [pl.col(column).cast(pl.Float64, strict=False) for column in NUMERIC_PREDICTORS]
    ).to_numpy()
    categorical: list[npt.NDArray[np.float64]] = []
    for column in CATEGORICAL_PREDICTORS:
        values = frame[column].cast(pl.String).fill_null("__missing__")
        levels = values.unique().sort().to_list()
        mapping = {value: code for code, value in enumerate(levels)}
        categorical.append(values.replace_strict(mapping).cast(pl.Float64).to_numpy())
    matrix = np.column_stack([numeric, *categorical]).astype(np.float64, copy=False)
    categorical_indices = list(
        range(len(NUMERIC_PREDICTORS), len(NUMERIC_PREDICTORS) + len(categorical))
    )
    return matrix, categorical_indices


def _folds(parcel_id: pl.Series, n_folds: int, seed: int) -> npt.NDArray[np.int64]:
    hashed = parcel_id.cast(pl.String).hash(seed=seed).to_numpy()
    return (hashed % n_folds).astype(np.int64)


def _fit_predict(
    matrix: npt.NDArray[np.float64],
    target: npt.NDArray[np.float64],
    reference: npt.NDArray[np.bool_],
    folds: npt.NDArray[np.int64],
    categorical_indices: list[int],
    *,
    n_folds: int,
    seed: int,
    rounds: int,
) -> npt.NDArray[np.float64]:
    predictions = np.full(len(target), np.nan, dtype=np.float64)
    params = {
        "objective": "regression_l1",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 80,
        "feature_fraction": 0.85,
        "lambda_l2": 1.0,
        "verbosity": -1,
        "seed": seed,
        "num_threads": 0,
    }
    for fold in range(n_folds):
        train = reference & (folds != fold)
        score = folds == fold
        dataset = lgb.Dataset(
            matrix[train],
            label=target[train],
            categorical_feature=categorical_indices,
            free_raw_data=True,
        )
        model = lgb.train(params, dataset, num_boost_round=rounds)
        predictions[score] = model.predict(matrix[score])
    return predictions


def _empty_result(frame: pl.DataFrame, *, reason: str) -> CharacteristicQualityResult:
    out = frame.select("parcel_id").with_columns(
        *[
            pl.lit(False).alias(column)
            if column
            in {
                "quality_area_outlier",
                "quality_zero_bed_bath_conflict",
                "quality_characteristic_outlier",
            }
            else pl.lit(None, dtype=pl.Float64).alias(column)
            for column in QUALITY_COLUMNS
        ]
    )
    return CharacteristicQualityResult(
        frame=out,
        metadata={"model_version": MODEL_VERSION, "status": "not_fit", "reason": reason},
    )


def add_characteristic_quality(
    frame: pl.DataFrame, quality: pl.LazyFrame | pl.DataFrame | None
) -> pl.DataFrame:
    """Join the versioned quality mart while keeping feature schemas stable."""
    if quality is None:
        return frame.with_columns(
            *[
                pl.lit(False).alias(column)
                if column
                in {
                    "quality_area_outlier",
                    "quality_zero_bed_bath_conflict",
                    "quality_characteristic_outlier",
                }
                else pl.lit(None, dtype=pl.Float64).alias(column)
                for column in QUALITY_COLUMNS
                if column not in frame.columns
            ]
        )
    quality_frame = quality.collect() if isinstance(quality, pl.LazyFrame) else quality
    available = [column for column in QUALITY_COLUMNS if column in quality_frame.columns]
    return frame.join(quality_frame.select("parcel_id", *available), on="parcel_id", how="left")


def crossfit_characteristic_quality(
    frame: pl.DataFrame,
    *,
    n_folds: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
    min_reference_rows: int = 1_000,
) -> CharacteristicQualityResult:
    """Reconstruct key characteristics with parcel-level out-of-fold models.

    The area model learns only from records where OPA living area and the
    independent building envelope are broadly coherent.  Calibration uses a
    wider held-out population so the reference interval is not falsely tight.
    Bed/bath models learn only from positive reported values and never consume
    the recorded living-area value; they use the same independent predictors
    as the area model.
    """
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    if frame["parcel_id"].n_unique() != frame.height:
        raise ValueError("characteristic-quality input must have one row per parcel")

    data = _ensure_columns(frame)
    matrix, categorical_indices = _matrix(data)
    fold = _folds(data["parcel_id"], n_folds, seed)

    area = data["char_livable_area"].cast(pl.Float64, strict=False).to_numpy()
    ratio = data["char_livable_to_footprint_gross_ratio"].cast(pl.Float64, strict=False).to_numpy()
    gross = data["char_footprint_gross_sqft"].cast(pl.Float64, strict=False).to_numpy()
    area_conflict = (
        data["char_area_conflict"].cast(pl.Float64, strict=False).fill_null(0.0).to_numpy() > 0
    )
    plausible_area = np.isfinite(area) & (area >= _AREA_MIN) & (area <= _AREA_MAX)
    coherent_area = (
        plausible_area
        & np.isfinite(ratio)
        & (ratio >= _COHERENT_RATIO_LOW)
        & (ratio <= _COHERENT_RATIO_HIGH)
        & ~area_conflict
    )
    if int(coherent_area.sum()) < min_reference_rows:
        return _empty_result(data, reason="too_few_coherent_area_records")
    if any(int((coherent_area & (fold != value)).sum()) < 100 for value in range(n_folds)):
        return _empty_result(data, reason="too_few_area_records_per_fold")

    expected_log_area = _fit_predict(
        matrix,
        np.log(np.clip(area, 1.0, None)),
        coherent_area,
        fold,
        categorical_indices,
        n_folds=n_folds,
        seed=seed,
        rounds=180,
    )
    expected_area = np.exp(expected_log_area)

    calibration = plausible_area & np.isfinite(gross) & (gross > 0) & ~area_conflict
    residual = np.log(np.clip(area, 1.0, None)) - expected_log_area
    calibration_residual = residual[calibration & np.isfinite(residual)]
    residual_center = float(np.median(calibration_residual))
    residual_sigma = float(1.4826 * np.median(np.abs(calibration_residual - residual_center)))
    residual_sigma = max(residual_sigma, 1e-6)
    residual_q05, residual_q95 = np.quantile(calibration_residual, [0.05, 0.95])
    centered_abs_z = np.abs((calibration_residual - residual_center) / residual_sigma)
    outlier_z = float(np.quantile(centered_abs_z, _AREA_OUTLIER_QUANTILE))
    area_z = (residual - residual_center) / residual_sigma

    counts: dict[str, npt.NDArray[np.float64]] = {}
    count_references: dict[str, int] = {}
    for column, maximum in (("char_beds", 20.0), ("char_baths", 20.0)):
        observed = data[column].cast(pl.Float64, strict=False).to_numpy()
        reference = coherent_area & np.isfinite(observed) & (observed > 0) & (observed <= maximum)
        if int(reference.sum()) < min_reference_rows:
            return _empty_result(data, reason=f"too_few_positive_{column}_records")
        predicted = _fit_predict(
            matrix,
            np.log1p(np.clip(observed, 0.0, None)),
            reference,
            fold,
            categorical_indices,
            n_folds=n_folds,
            seed=seed + (1 if column == "char_beds" else 2),
            rounds=120,
        )
        counts[column] = np.maximum(np.expm1(predicted), 0.0)
        count_references[column] = int(reference.sum())

    beds = data["char_beds"].cast(pl.Float64, strict=False).to_numpy()
    baths = data["char_baths"].cast(pl.Float64, strict=False).to_numpy()
    bed_zero = np.isfinite(beds) & (beds <= 0)
    bath_zero = np.isfinite(baths) & (baths <= 0)
    bed_conflict = np.where(bed_zero, counts["char_beds"], 0.0)
    bath_conflict = np.where(bath_zero, counts["char_baths"], 0.0)
    zero_pair_conflict = bed_zero & bath_zero & (bed_conflict >= 1.0) & (bath_conflict >= 0.75)
    # A continuous score is safer for later ablations than a hand-tuned all-or-
    # nothing warning.  Three area sigmas maps to 1; expected 3 beds/1.5 baths
    # with zeros also maps to roughly 1.
    characteristic_score = np.maximum.reduce(
        [
            np.abs(area_z) / 3.0,
            bed_conflict / 3.0,
            bath_conflict / 1.5,
        ]
    )
    score_outlier_threshold = float(
        np.quantile(
            characteristic_score[np.isfinite(characteristic_score)],
            1.0 - 0.05,
        )
    )

    output = data.select("parcel_id").with_columns(
        pl.Series("quality_expected_livable_area", expected_area),
        pl.Series("quality_area_reference_low_90", expected_area * np.exp(residual_q05)),
        pl.Series("quality_area_reference_high_90", expected_area * np.exp(residual_q95)),
        pl.Series("quality_area_ratio_to_expected", area / expected_area),
        pl.Series("quality_area_log_residual", residual),
        pl.Series("quality_area_disagreement_z", area_z),
        pl.Series("quality_area_outlier", np.abs(area_z) > outlier_z),
        pl.Series("quality_expected_beds", counts["char_beds"]),
        pl.Series("quality_expected_baths", counts["char_baths"]),
        pl.Series("quality_bed_zero_conflict", bed_conflict),
        pl.Series("quality_bath_zero_conflict", bath_conflict),
        pl.Series("quality_zero_bed_bath_conflict", zero_pair_conflict),
        pl.Series("quality_characteristic_conflict_score", characteristic_score),
        pl.Series(
            "quality_characteristic_outlier",
            characteristic_score >= score_outlier_threshold,
        ),
    )
    metadata: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "status": "ok",
        "folds": n_folds,
        "seed": seed,
        "predictors": [*NUMERIC_PREDICTORS, *CATEGORICAL_PREDICTORS],
        "prohibited_predictors": ["sale_price", "opa_market_value", "asmt_market_value_sale_year"],
        "area_reference_rows": int(coherent_area.sum()),
        "area_calibration_rows": int(len(calibration_residual)),
        "bed_reference_rows": count_references["char_beds"],
        "bath_reference_rows": count_references["char_baths"],
        "area_residual_center": residual_center,
        "area_residual_sigma": residual_sigma,
        "area_residual_q05": float(residual_q05),
        "area_residual_q95": float(residual_q95),
        "area_outlier_abs_z_threshold": outlier_z,
        "characteristic_outlier_quantile": 0.95,
        "characteristic_outlier_score_threshold": score_outlier_threshold,
    }
    return CharacteristicQualityResult(frame=output, metadata=metadata)


def _source_frame(opa: pl.LazyFrame, building_footprints: pl.LazyFrame | None) -> pl.DataFrame:
    from philly_fair_measure.config import CONDO_ACCOUNT_PREFIX

    frame = (
        opa.filter(
            pl.col("category_code_description").is_in(RESIDENTIAL_CATEGORIES)
            & ~pl.col("parcel_number").str.starts_with(CONDO_ACCOUNT_PREFIX)
        )
        .select(
            pl.col("parcel_number").alias("parcel_id"),
            pl.col("zip_code").cast(pl.String).str.slice(0, 5).alias("loc_zip5"),
            pl.col("category_code_description").alias("char_category"),
            *_CHAR_RENAMES,
            *[column for column in _LOC_RENAMES if column != "street_code"],
        )
        .collect()
        .rename(
            {
                **_CHAR_RENAMES,
                **{
                    source: target
                    for source, target in _LOC_RENAMES.items()
                    if source != "street_code"
                },
            }
        )
        .with_columns(style_expr(), era_expr(), pl.lit(None).alias("mkt_knn_log_ppsf"))
    )
    return add_building_structure_features(frame, building_footprints)


def build_characteristic_quality(
    data_dir: Path | None = None,
    *,
    n_folds: int = DEFAULT_FOLDS,
) -> BuildResult:
    root = data_dir if data_dir is not None else config.data_dir()
    opa_path = root / "staged" / "opa_properties.parquet"
    footprint_path = root / "staged" / "building_footprints.parquet"
    if not opa_path.exists():
        raise FileNotFoundError(f"{opa_path} missing; run `fair-measure stage` first")
    footprints = pl.scan_parquet(footprint_path) if footprint_path.exists() else None
    source = _source_frame(pl.scan_parquet(opa_path), footprints)
    result = crossfit_characteristic_quality(source, n_folds=n_folds)
    if result.metadata.get("status") != "ok":
        raise RuntimeError(f"characteristic-quality model was not fit: {result.metadata}")

    inputs: list[InputRef] = []
    for path in (opa_path, footprint_path):
        if not path.exists():
            continue
        manifest = read_derived_manifest(path)
        inputs.append(
            InputRef(
                dataset=f"{manifest.layer}/{manifest.table}",
                fetched_at=manifest.built_at.isoformat(),
            )
        )
    path, manifest = write_derived_table(
        result.frame,
        root,
        "marts",
        "characteristic_quality",
        inputs,
        notes=(
            "cross-fitted current-only characteristic plausibility; diagnostic only; "
            "no sale price or assessment value inputs"
        ),
    )
    metadata_path = path.with_name("characteristic_quality.metadata.json")
    metadata_path.write_text(json.dumps(result.metadata, indent=2, sort_keys=True) + "\n")
    logger.info("characteristic quality -> %s", path)
    return BuildResult(path=path, manifest=manifest, metadata_path=metadata_path)
