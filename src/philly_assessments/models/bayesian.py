"""Bayesian hierarchical valuation model (Milestone 7).

A hierarchical hedonic regression with partial pooling over geography:

    log(price) ~ Normal(alpha_tract + X @ beta, sigma)
    alpha_tract ~ Normal(alpha_ward, tau_tract)     [non-centered]
    alpha_ward  ~ Normal(mu_city, tau_ward)         [non-centered]

What this adds over the LightGBM baseline is not point accuracy (a linear
hedonic will usually lose to boosted trees) but **calibrated uncertainty**:
every property gets a full predictive distribution, and we report the
empirical coverage of the 90% predictive interval on the out-of-time test set.
A property whose OPA assessment falls far outside its predictive interval is a
principled staleness candidate — that is the payoff of this layer.

Covariates are a compact, interpretable subset (standardized on the training
slice; medians imputed with the block-roll missingness kept as an indicator).
Condition codes enter as ordinals — a deliberate v0 simplification.

Unseen geography at prediction time degrades gracefully: unseen tract draws a
fresh tract effect around its ward; unseen ward falls back to the city level.
Uses the same chronological test split as the baseline for comparability.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

from philly_assessments import __version__, config
from philly_assessments.ingest.manifests import (
    DerivedManifest,
    InputRef,
    read_derived_manifest,
    write_derived_manifest,
)
from philly_assessments.models.baseline import _load_frame
from philly_assessments.models.metrics import evaluate_estimates

logger = logging.getLogger(__name__)

PI_LOW, PI_HIGH = 0.05, 0.95

_LOG1P_COVARIATES = {
    "char_livable_area": "log_livable_area",
    "char_lot_area": "log_lot_area",
    "mkt_block_roll_mean_price": "log_block_roll",
}
_LINEAR_COVARIATES = ["char_beds", "char_baths", "char_year_built", "time_sale_epoch_days"]
_ORDINAL_COVARIATES = ["char_exterior_condition", "char_interior_condition"]


@dataclass
class CovariateEncoder:
    """Impute-with-median + standardize, with parameters fitted on the train slice."""

    names: list[str]
    medians: dict[str, float]
    means: dict[str, float]
    stds: dict[str, float]

    @classmethod
    def fit(cls, df: pl.DataFrame) -> CovariateEncoder:
        raw = _raw_covariates(df)
        names = [c for c in raw.columns if c != "block_roll_missing"]
        medians, means, stds = {}, {}, {}
        for name in names:
            values = raw[name].drop_nulls().to_numpy()
            medians[name] = float(np.median(values)) if len(values) else 0.0
            filled = raw[name].fill_null(medians[name]).to_numpy()
            means[name] = float(np.mean(filled))
            stds[name] = float(np.std(filled)) or 1.0
        return cls(names=names, medians=medians, means=means, stds=stds)

    def transform(self, df: pl.DataFrame) -> np.ndarray:
        raw = _raw_covariates(df)
        columns = [
            (raw[name].fill_null(self.medians[name]).to_numpy() - self.means[name])
            / self.stds[name]
            for name in self.names
        ]
        columns.append(raw["block_roll_missing"].to_numpy().astype(np.float64))
        return np.column_stack(columns)

    @property
    def feature_names(self) -> list[str]:
        return [*self.names, "block_roll_missing"]


def _raw_covariates(df: pl.DataFrame) -> pl.DataFrame:
    exprs = [
        pl.col(src).cast(pl.Float64).log1p().alias(dst)
        for src, dst in _LOG1P_COVARIATES.items()
    ]
    exprs += [pl.col(c).cast(pl.Float64) for c in _LINEAR_COVARIATES]
    exprs += [
        pl.col(c).cast(pl.String).cast(pl.Int32, strict=False).cast(pl.Float64)
        for c in _ORDINAL_COVARIATES
    ]
    exprs.append(pl.col("mkt_block_roll_mean_price").is_null().alias("block_roll_missing"))
    return df.select(exprs)


@dataclass
class GeoIndex:
    wards: list[str]
    tracts: list[str]
    tract_to_ward_ix: np.ndarray  # ward index of each known tract

    @classmethod
    def fit(cls, df: pl.DataFrame) -> GeoIndex:
        pairs = (
            df.group_by("loc_census_tract_raw", "loc_ward")
            .agg(pl.len())
            .sort("len", descending=True)
            .unique(subset=["loc_census_tract_raw"], keep="first")
        )
        wards = sorted(df["loc_ward"].cast(pl.String).fill_null("__none__").unique().to_list())
        ward_ix = {w: i for i, w in enumerate(wards)}
        tracts, tract_ward = [], []
        for row in pairs.sort("loc_census_tract_raw").to_dicts():
            tracts.append(str(row["loc_census_tract_raw"]))
            tract_ward.append(ward_ix.get(str(row["loc_ward"]), 0))
        return cls(wards=wards, tracts=tracts, tract_to_ward_ix=np.array(tract_ward))

    def tract_indices(self, df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(tract index or -1 if unseen, ward index or -1 if unseen) per row."""
        tract_ix = {t: i for i, t in enumerate(self.tracts)}
        ward_ix = {w: i for i, w in enumerate(self.wards)}
        tract = np.array(
            [tract_ix.get(str(v), -1) for v in df["loc_census_tract_raw"].to_list()]
        )
        ward = np.array([ward_ix.get(str(v), -1) for v in df["loc_ward"].to_list()])
        return tract, ward


def _fit_posterior(
    x: np.ndarray,
    y: np.ndarray,
    tract_idx: np.ndarray,
    geo: GeoIndex,
    *,
    draws: int,
    tune: int,
    chains: int,
    cores: int,
    seed: int,
):
    import pymc as pm

    coords = {
        "ward": geo.wards,
        "tract": geo.tracts,
        "covariate": [f"x{i}" for i in range(x.shape[1])],
    }
    with pm.Model(coords=coords):
        mu_city = pm.Normal("mu_city", 12.0, 2.0)
        tau_ward = pm.HalfNormal("tau_ward", 0.5)
        z_ward = pm.Normal("z_ward", 0.0, 1.0, dims="ward")
        alpha_ward = pm.Deterministic("alpha_ward", mu_city + tau_ward * z_ward, dims="ward")

        tau_tract = pm.HalfNormal("tau_tract", 0.5)
        z_tract = pm.Normal("z_tract", 0.0, 1.0, dims="tract")
        alpha_tract = pm.Deterministic(
            "alpha_tract", alpha_ward[geo.tract_to_ward_ix] + tau_tract * z_tract, dims="tract"
        )

        beta = pm.Normal("beta", 0.0, 1.0, dims="covariate")
        sigma = pm.HalfNormal("sigma", 0.5)
        pm.Normal("obs", alpha_tract[tract_idx] + x @ beta, sigma, observed=y)

        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            # sequential chains by default: parallel chains fork the process on
            # macOS and segfault under multithreaded BLAS with large datasets
            cores=cores,
            random_seed=seed,
            target_accept=0.9,
            progressbar=False,
        )
    return idata


def _stack_draws(idata, name: str, max_draws: int, rng: np.random.Generator) -> np.ndarray:
    values = idata.posterior[name].values  # (chains, draws, ...)
    flat = values.reshape(-1, *values.shape[2:])
    if len(flat) > max_draws:
        flat = flat[rng.choice(len(flat), size=max_draws, replace=False)]
    return flat


def _predict_price_draws(
    idata,
    x: np.ndarray,
    tract: np.ndarray,
    ward: np.ndarray,
    *,
    max_draws: int,
    seed: int,
) -> np.ndarray:
    """(n_draws, n_rows) posterior-predictive draws of price (levels, not logs)."""
    rng = np.random.default_rng(seed)
    keep = np.random.default_rng(seed)  # same subset across parameters
    alpha_tract = _stack_draws(idata, "alpha_tract", max_draws, keep)
    keep = np.random.default_rng(seed)
    alpha_ward = _stack_draws(idata, "alpha_ward", max_draws, keep)
    keep = np.random.default_rng(seed)
    mu_city = _stack_draws(idata, "mu_city", max_draws, keep)
    keep = np.random.default_rng(seed)
    tau_tract = _stack_draws(idata, "tau_tract", max_draws, keep)
    keep = np.random.default_rng(seed)
    beta = _stack_draws(idata, "beta", max_draws, keep)
    keep = np.random.default_rng(seed)
    sigma = _stack_draws(idata, "sigma", max_draws, keep)

    n_draws = len(beta)
    alpha = np.empty((n_draws, len(tract)))
    seen = tract >= 0
    alpha[:, seen] = alpha_tract[:, tract[seen]]
    unseen_tract = (~seen) & (ward >= 0)
    if unseen_tract.any():
        alpha[:, unseen_tract] = alpha_ward[:, ward[unseen_tract]] + tau_tract[
            :, None
        ] * rng.standard_normal((n_draws, int(unseen_tract.sum())))
    unseen_all = (~seen) & (ward < 0)
    if unseen_all.any():
        alpha[:, unseen_all] = mu_city[:, None]

    mu = alpha + beta @ x.T
    log_pred = mu + sigma[:, None] * rng.standard_normal(mu.shape)
    return np.exp(log_pred)


@dataclass(frozen=True)
class BayesianRunResult:
    run_dir: Path
    run_id: str
    overall: dict
    evaluation: pl.DataFrame


def train_bayesian(
    data_dir: Path | None = None,
    *,
    test_fraction: float = 0.1,
    draws: int = 800,
    tune: int = 800,
    chains: int = 2,
    cores: int = 1,
    max_prediction_draws: int = 500,
    seed: int = 42,
) -> BayesianRunResult:
    root = data_dir if data_dir is not None else config.data_dir()
    mart_path = root / "marts" / "sale_features.parquet"
    if not mart_path.exists():
        raise FileNotFoundError(f"{mart_path} missing; run `philly build-features` first")

    df = _load_frame(mart_path)
    n_test = max(1, int(df.height * test_fraction))
    train_df, test_df = df.head(df.height - n_test), df.tail(n_test)
    logger.info(
        "bayesian: %s train / %s test rows, sampling %d draws x %d chains",
        f"{train_df.height:,}",
        f"{test_df.height:,}",
        draws,
        chains,
    )

    encoder = CovariateEncoder.fit(train_df)
    geo = GeoIndex.fit(train_df)
    x_train = encoder.transform(train_df)
    y_train = np.log(train_df["sale_price"].to_numpy())
    tract_train, _ = geo.tract_indices(train_df)
    # training rows always have a known tract by construction (fitted on train)

    idata = _fit_posterior(
        x_train,
        y_train,
        tract_train,
        geo,
        draws=draws,
        tune=tune,
        chains=chains,
        cores=cores,
        seed=seed,
    )

    x_test = encoder.transform(test_df)
    tract_test, ward_test = geo.tract_indices(test_df)
    price_draws = _predict_price_draws(
        idata, x_test, tract_test, ward_test, max_draws=max_prediction_draws, seed=seed
    )
    point = np.median(price_draws, axis=0)
    pi_low = np.quantile(price_draws, PI_LOW, axis=0)
    pi_high = np.quantile(price_draws, PI_HIGH, axis=0)

    sale_price = test_df["sale_price"].to_numpy()
    covered = (sale_price >= pi_low) & (sale_price <= pi_high)

    from philly_assessments.models.baseline import _segments

    rows = []
    for segment_type, segment, mask in _segments(test_df):
        m = mask.to_numpy()
        rows.append(
            {
                "model": "bayesian_hierarchical",
                "segment_type": segment_type,
                "segment": segment,
                **evaluate_estimates(point[m], sale_price[m]),
                "coverage_90": float(np.mean(covered[m])) if m.any() else None,
                "mean_pi_width_rel": (
                    float(np.mean((pi_high[m] - pi_low[m]) / point[m])) if m.any() else None
                ),
            }
        )
    evaluation = pl.DataFrame(rows)
    overall = evaluation.filter(pl.col("segment_type") == "overall").to_dicts()[0]

    hyper_summary = []
    for name in ("mu_city", "tau_ward", "tau_tract", "sigma"):
        flat = idata.posterior[name].values.reshape(-1)
        hyper_summary.append(
            {
                "parameter": name,
                "mean": float(flat.mean()),
                "sd": float(flat.std()),
                "q05": float(np.quantile(flat, 0.05)),
                "q95": float(np.quantile(flat, 0.95)),
            }
        )
    beta_flat = idata.posterior["beta"].values.reshape(-1, x_train.shape[1])
    for i, name in enumerate(encoder.feature_names):
        hyper_summary.append(
            {
                "parameter": f"beta[{name}]",
                "mean": float(beta_flat[:, i].mean()),
                "sd": float(beta_flat[:, i].std()),
                "q05": float(np.quantile(beta_flat[:, i], 0.05)),
                "q95": float(np.quantile(beta_flat[:, i], 0.95)),
            }
        )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-bayesian"
    run_dir = root / "models" / f"run_id={run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "params.json").write_text(
        json.dumps(
            {
                "draws": draws,
                "tune": tune,
                "chains": chains,
                "test_fraction": test_fraction,
                "max_prediction_draws": max_prediction_draws,
                "seed": seed,
                "covariates": encoder.feature_names,
                "n_wards": len(geo.wards),
                "n_tracts": len(geo.tracts),
                "test_start_date": str(test_df["sale_date"].min()),
            },
            indent=2,
        )
        + "\n"
    )
    pl.DataFrame(hyper_summary).write_parquet(run_dir / "posterior_summary.parquet")
    evaluation.write_parquet(run_dir / "evaluation.parquet")
    test_df.select("sale_id", "parcel_id", "sale_date", "sale_price").with_columns(
        pl.Series("pred_median", point),
        pl.Series("pi_low_90", pi_low),
        pl.Series("pi_high_90", pi_high),
        pl.Series("covered_90", covered),
        pl.Series("opa_assessment", test_df["asmt_market_value_sale_year"].to_numpy()),
    ).write_parquet(run_dir / "predictions.parquet")

    mart_manifest = read_derived_manifest(mart_path)
    manifest = DerivedManifest(
        layer="models",
        table=run_id,
        built_at=datetime.now(UTC),
        row_count=test_df.height,
        inputs=[
            InputRef(
                dataset=f"{mart_manifest.layer}/{mart_manifest.table}",
                fetched_at=mart_manifest.built_at.isoformat(),
            )
        ],
        package_version=__version__,
        notes="row_count is the test-set size; see params.json",
    )
    write_derived_manifest(manifest, run_dir / "run.parquet")
    logger.info("bayesian run %s -> %s", run_id, run_dir)
    return BayesianRunResult(
        run_dir=run_dir, run_id=run_id, overall=overall, evaluation=evaluation
    )
