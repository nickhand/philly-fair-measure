"""Bayesian hierarchical valuation model, v2 (Milestone 7 + plan v2 Tier 3).

A robust heteroscedastic hedonic with partial pooling over *learned* geography
and a finite-rank spatial surface, trained on time-adjusted prices:

    y_i = log(price_i) + time_adj_i                      [reference-month dollars]
    y_i ~ StudentT(nu, mu_i, sigma_i)                    [robust to fat tails]
    mu_i = alpha_area[a_i] + X_i @ beta + B_i @ w        [B: fixed RBF basis]
    alpha_area ~ Normal(alpha_district, tau_area)        [non-centered]
    alpha_district ~ Normal(mu_city, tau_district)       [non-centered]
    log sigma_i = g0 + g @ Z_i                           [evidence-density terms]

Modern-practice choices and why (docs/research-notes.md):

- **Student-t likelihood** (nu learned): sale-price tails inflated the v1
  Normal sigma to 0.45, making honest intervals very wide; a robust likelihood
  narrows intervals without sacrificing coverage.
- **Time-adjusted target** (OPA practice, shared with the v2 LightGBM): kills
  the linear-time-trend extrapolation bias (v1 median ratio 1.12).
- **Learned geography** for pooling: district (18) → market area (350) from
  features/market_areas.py replaces ward → tract; boundaries follow price
  discontinuities rather than administrative lines.
- **Fixed RBF spatial basis** (~64 k-means centers, shared bandwidth): a
  finite-rank GP approximation in the HSGP spirit, with the basis chosen
  a priori so that scoring from persisted draws is exact simple linear
  algebra (an honest tradeoff: lengthscale fixed, not learned).
- **Heteroscedastic sigma**: predictive uncertainty widens where evidence is
  thin (missing block roll, distant kNN neighbors) — sharper where dense,
  honest where sparse.
- **Conditional calibration**: coverage is reported by district and style, not
  just overall (the spatially-weighted-conformal lesson: marginal coverage can
  hide local failure).

Repeat sales enter as a covariate, not a random effect: mkt_parcel_prev_log_
price_ref (the parcel's previous sale price in the reference frame) is a
direct prior estimate of y for the 62% of sales that are repeats. A full
per-parcel random effect was built and measured (--parcel-effect, ~29k
repeat-parcel params) and adds ~nothing over the covariate (COD 30.43->30.37,
width 1.324->1.340 at 150 draws) — only ~7% of test sales are train-repeat
parcels and only 3,806 parcels have 3+ sales where a latent beats "last
price"; it even widens intervals slightly by marginalizing unknown-house
quality as noise over the non-repeat majority. Kept opt-in, off by default.

Unseen geography degrades gracefully: unseen market area draws a fresh area
effect around its district; unseen district falls back to the city level.
Chains run sequentially by default (cores=1): parallel chains fork on macOS
and segfault under multithreaded BLAS at this data size.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from arviz import InferenceData

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
N_RBF_CENTERS = 64
MIN_DISTRICT_SEGMENT_N = 200

_LOG1P_COVARIATES = {
    "char_livable_area": "log_livable_area",
    "char_lot_area": "log_lot_area",
    "mkt_block_roll_mean_price": "log_block_roll",
    "mkt_block_roll_ppsf": "log_block_roll_ppsf",
}
_LINEAR_COVARIATES = [
    "char_beds",
    "char_baths",
    "char_year_built",
    "mkt_knn_log_ppsf",
    "mkt_area_level_log_ppsf",
    "mkt_knn_mean_dist_m",
    # repeat-sales carry-forward: the parcel's previous sale price in the
    # index reference frame — a direct prior estimate of y for the 62% of
    # sales that are repeats. Paired with a missing indicator so non-repeats
    # aren't imputed to a misleading "average previous price".
    "mkt_parcel_prev_log_price_ref",
]
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
        names = [c for c in raw.columns if not c.endswith("_missing")]
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
        columns += [
            raw[name].to_numpy().astype(np.float64) for name in self._missing_names
        ]
        return np.column_stack(columns)

    @property
    def _missing_names(self) -> list[str]:
        # stable order: derived from the covariate definitions, not the run
        return ["block_roll_missing", "prev_price_missing"]

    @property
    def feature_names(self) -> list[str]:
        return [*self.names, *self._missing_names]


def _raw_covariates(df: pl.DataFrame) -> pl.DataFrame:
    # fill_nan: float NaN (e.g. from upstream 0/0) is not null in polars and
    # would otherwise poison the encoder's mean/std for the whole column
    exprs = [
        pl.col(src).cast(pl.Float64).fill_nan(None).log1p().alias(dst)
        for src, dst in _LOG1P_COVARIATES.items()
    ]
    exprs += [pl.col(c).cast(pl.Float64).fill_nan(None) for c in _LINEAR_COVARIATES]
    exprs += [
        pl.col(c).cast(pl.String).cast(pl.Int32, strict=False).cast(pl.Float64)
        for c in _ORDINAL_COVARIATES
    ]
    exprs.append(pl.col("mkt_block_roll_mean_price").is_null().alias("block_roll_missing"))
    exprs.append(
        pl.col("mkt_parcel_prev_log_price_ref")
        .cast(pl.Float64)
        .fill_nan(None)
        .is_null()
        .alias("prev_price_missing")
    )
    return df.select(exprs)


@dataclass
class GeoIndex:
    """Fine-within-coarse geography index (market areas within districts)."""

    coarse: list[str]
    fine: list[str]
    fine_to_coarse_ix: np.ndarray

    @classmethod
    def fit(
        cls, df: pl.DataFrame, fine_col: str = "loc_market_area",
        coarse_col: str = "loc_district",
    ) -> GeoIndex:
        pairs = (
            df.group_by(fine_col, coarse_col)
            .agg(pl.len())
            .sort("len", descending=True)
            .unique(subset=[fine_col], keep="first")
        )
        coarse = sorted(df[coarse_col].cast(pl.String).fill_null("__none__").unique().to_list())
        coarse_ix = {value: i for i, value in enumerate(coarse)}
        fine, fine_coarse = [], []
        for row in pairs.sort(fine_col).to_dicts():
            fine.append(str(row[fine_col]))
            fine_coarse.append(coarse_ix.get(str(row[coarse_col]), 0))
        return cls(coarse=coarse, fine=fine, fine_to_coarse_ix=np.array(fine_coarse))

    def indices(
        self, df: pl.DataFrame, fine_col: str = "loc_market_area",
        coarse_col: str = "loc_district",
    ) -> tuple[np.ndarray, np.ndarray]:
        """(fine index or -1 if unseen, coarse index or -1 if unseen) per row."""
        fine_ix = {value: i for i, value in enumerate(self.fine)}
        coarse_ix = {value: i for i, value in enumerate(self.coarse)}
        fine = np.array([fine_ix.get(str(v), -1) for v in df[fine_col].to_list()])
        coarse = np.array([coarse_ix.get(str(v), -1) for v in df[coarse_col].to_list()])
        return fine, coarse


@dataclass
class ParcelIndex:
    """Parcel random-effect index, identified only by repeat sales.

    A per-parcel latent quality term is unidentified for single-sale parcels
    (confounded with the residual), so only parcels with >= `min_sales`
    training sales get an effect; all others map to a fixed zero slot. This
    keeps the parameter count to the repeat parcels and is the statistically
    honest structure — the effect exists exactly where the data can estimate
    it. Leakage discipline: fitted on TRAIN parcels only; at scoring a known
    repeat parcel uses its posterior effect (its earlier sale genuinely
    precedes the later one, like mkt_parcel_prev_price), while an unseen
    parcel's effect is marginalized as tau_parcel noise."""

    parcels: list[str]  # repeat parcels, in index order
    min_sales: int = 2

    @classmethod
    def fit(cls, df: pl.DataFrame, min_sales: int = 2) -> ParcelIndex:
        counts = df.group_by("parcel_id").len().filter(pl.col("len") >= min_sales)
        return cls(parcels=sorted(counts["parcel_id"].to_list()), min_sales=min_sales)

    @property
    def n(self) -> int:
        return len(self.parcels)

    def mapped(self, df: pl.DataFrame) -> np.ndarray:
        """Row -> parcel index, or n (the zero slot) for singleton/unseen."""
        ix = {p: i for i, p in enumerate(self.parcels)}
        return np.array([ix.get(p, self.n) for p in df["parcel_id"].to_list()])

    def seen(self, df: pl.DataFrame) -> np.ndarray:
        """Row -> parcel index or -1 (used by scoring to split known/unknown)."""
        ix = {p: i for i, p in enumerate(self.parcels)}
        return np.array([ix.get(p, -1) for p in df["parcel_id"].to_list()])


@dataclass
class RBFBasis:
    """Fixed Gaussian basis over projected coordinates: a finite-rank GP surface."""

    centers: np.ndarray  # (m, 2) in meters
    bandwidth_m: float

    @classmethod
    def fit(cls, xy: np.ndarray, n_centers: int = N_RBF_CENTERS, seed: int = 42) -> RBFBasis:
        from sklearn.cluster import KMeans

        centers = (
            KMeans(n_clusters=n_centers, n_init=4, random_state=seed).fit(xy).cluster_centers_
        )
        # bandwidth ~ 1.5x median nearest-center spacing: overlapping, smooth
        from scipy.spatial import cKDTree

        dist, _ = cKDTree(centers).query(centers, k=2)
        bandwidth = 1.5 * float(np.median(dist[:, 1]))
        return cls(centers=centers, bandwidth_m=bandwidth)

    def transform(self, xy: np.ndarray) -> np.ndarray:
        d2 = ((xy[:, None, :] - self.centers[None, :, :]) ** 2).sum(axis=2)
        return np.asarray(np.exp(-0.5 * d2 / self.bandwidth_m**2), dtype=np.float64)


def _xy(df: pl.DataFrame) -> np.ndarray:
    from philly_assessments.features.market_areas import project_xy

    out = df.select(
        pl.col("loc_lon").alias("lon"), pl.col("loc_lat").alias("lat")
    ).with_columns(*project_xy(pl.col("lon"), pl.col("lat")))
    xy = out.select("x_m", "y_m").to_numpy()
    return np.asarray(np.nan_to_num(xy, nan=0.0), dtype=np.float64)


SIGMA_TERM_NAMES = [
    "block_roll_missing",
    "knn_dist",
    "style_twin",
    "style_detached",
    "style_other",
]


def _sigma_design(df: pl.DataFrame) -> np.ndarray:
    """Design for log sigma: evidence density plus style, per the conditional
    calibration finding (coverage 80-99.6% by district/style before v2.1)."""
    missing = df["mkt_block_roll_mean_price"].is_null().to_numpy().astype(np.float64)
    dist = df["mkt_knn_mean_dist_m"].cast(pl.Float64).fill_null(500.0).to_numpy()
    style = df["char_style"].cast(pl.String).fill_null("unknown").to_numpy()
    return np.column_stack(
        [
            missing,
            np.log1p(dist) / 10.0,
            (style == "twin").astype(np.float64),
            (style == "detached").astype(np.float64),
            ((style == "other") | (style == "unknown")).astype(np.float64),
        ]
    )


def _fit_posterior(
    x: np.ndarray,
    basis: np.ndarray | None,
    z_sigma: np.ndarray,
    y: np.ndarray,
    area_idx: np.ndarray,
    district_idx: np.ndarray,
    geo: GeoIndex,
    *,
    draws: int,
    tune: int,
    chains: int,
    cores: int,
    seed: int,
    nu_fixed: float | None,
    parcel_mapped: np.ndarray | None = None,
    n_parcels: int = 0,
) -> InferenceData:
    import pymc as pm

    coords = {
        "district": geo.coarse,
        "area": geo.fine,
        "covariate": [f"x{i}" for i in range(x.shape[1])],
        "sigma_term": [f"z{i}" for i in range(z_sigma.shape[1])],
    }
    if basis is not None:
        coords["basis"] = [f"b{i}" for i in range(basis.shape[1])]
    if parcel_mapped is not None:
        coords["parcel"] = [f"p{i}" for i in range(n_parcels)]
    with pm.Model(coords=coords):
        mu_city = pm.Normal("mu_city", 12.0, 2.0)
        tau_district = pm.HalfNormal("tau_district", 0.5)
        z_district = pm.Normal("z_district", 0.0, 1.0, dims="district")
        alpha_district = pm.Deterministic(
            "alpha_district", mu_city + tau_district * z_district, dims="district"
        )
        tau_area = pm.HalfNormal("tau_area", 0.3)
        z_area = pm.Normal("z_area", 0.0, 1.0, dims="area")
        alpha_area = pm.Deterministic(
            "alpha_area", alpha_district[geo.fine_to_coarse_ix] + tau_area * z_area, dims="area"
        )

        beta = pm.Normal("beta", 0.0, 1.0, dims="covariate")
        mu = alpha_area[area_idx] + x @ beta
        if parcel_mapped is not None:
            # per-parcel latent quality, identified by repeats (non-centered);
            # a zero slot at index n absorbs singleton/unseen parcels so the
            # effect is only estimated where the data can
            tau_parcel = pm.HalfNormal("tau_parcel", 0.3)
            z_parcel = pm.Normal("z_parcel", 0.0, 1.0, dims="parcel")
            u_parcel = pm.Deterministic("u_parcel", tau_parcel * z_parcel, dims="parcel")
            u_parcel_padded = pm.math.concatenate([u_parcel, [0.0]])
            mu = mu + u_parcel_padded[parcel_mapped]
        if basis is not None:
            # measured 2026-07-03: the overlapping RBF columns are collinear and
            # multiply a shared tau_gp — sampling slows >15x. Off by default;
            # the kNN covariate already carries the fine-grained surface.
            tau_gp = pm.HalfNormal("tau_gp", 0.3)
            w = pm.Normal("w_spatial", 0.0, 1.0, dims="basis")
            mu = mu + basis @ (tau_gp * w)

        g0 = pm.Normal("g0", -1.0, 1.0)
        g = pm.Normal("g", 0.0, 0.5, dims="sigma_term")
        tau_sigma_district = pm.HalfNormal("tau_sigma_district", 0.3)
        z_sigma_district = pm.Normal("z_sigma_district", 0.0, 1.0, dims="district")
        u_sigma_district = pm.Deterministic(
            "u_sigma_district", tau_sigma_district * z_sigma_district, dims="district"
        )
        sigma = pm.Deterministic(
            "sigma_obs",
            pm.math.exp(g0 + z_sigma @ g + u_sigma_district[district_idx]),
        )

        # learned nu couples every observation through one global parameter and
        # sampled brutally slowly at this scale (hours); a fixed moderate-tail
        # nu keeps the robustness at a fraction of the cost
        nu = pm.Gamma("nu", alpha=2.0, beta=0.1) if nu_fixed is None else nu_fixed

        pm.StudentT("obs", nu=nu, mu=mu, sigma=sigma, observed=y)

        # nutpie: Rust NUTS, several-fold faster than the default sampler and
        # runs parallel chains as in-process threads — which also sidesteps the
        # macOS fork/segfault issue that forced sequential chains previously
        sampler_kwargs: dict[str, str | int]
        try:
            import nutpie  # noqa: F401

            sampler_kwargs = {"nuts_sampler": "nutpie"}
        except ImportError:
            sampler_kwargs = {"cores": cores}
        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            random_seed=seed,
            target_accept=0.9,
            progressbar=False,
            **sampler_kwargs,
        )
    return idata


_DRAW_VARIABLES = (
    "alpha_area", "alpha_district", "mu_city", "tau_area",
    "beta", "tau_gp", "w_spatial", "g0", "g", "u_sigma_district",
    "tau_sigma_district", "nu", "u_parcel", "tau_parcel",
)


def _thin_draws(
    idata: InferenceData, max_draws: int, seed: int, nu_fixed: float | None = None
) -> dict[str, np.ndarray]:
    """Flatten chains and keep one common random subset of joint posterior draws."""
    out: dict[str, np.ndarray] = {}
    subset = None
    for name in _DRAW_VARIABLES:
        if name not in idata.posterior:
            continue
        values = idata.posterior[name].values  # (chains, draws, ...)
        flat = values.reshape(-1, *values.shape[2:])
        if subset is None:
            rng = np.random.default_rng(seed)
            subset = (
                np.arange(len(flat))
                if len(flat) <= max_draws
                else rng.choice(len(flat), size=max_draws, replace=False)
            )
        out[name] = flat[subset]
    if "nu" not in out:
        if nu_fixed is None:
            raise ValueError("posterior has no 'nu' draws and no nu_fixed was given")
        out["nu"] = np.full(len(out["beta"]), float(nu_fixed))
    return out


def predict_price_draws(
    draws: dict[str, np.ndarray],
    x: np.ndarray,
    basis: np.ndarray | None,
    z_sigma: np.ndarray,
    area: np.ndarray,
    district: np.ndarray,
    *,
    seed: int,
    time_adj_log: np.ndarray | None = None,
    parcel: np.ndarray | None = None,
) -> np.ndarray:
    """(n_draws, n_rows) posterior-predictive price draws at the sale/valuation
    date (levels): reference-month draws shifted back by `time_adj_log`."""
    rng = np.random.default_rng(seed)
    n_draws = len(draws["beta"])
    n_rows = len(area)

    alpha = np.empty((n_draws, n_rows))
    seen = area >= 0
    alpha[:, seen] = draws["alpha_area"][:, area[seen]]
    unseen_area = (~seen) & (district >= 0)
    if unseen_area.any():
        alpha[:, unseen_area] = draws["alpha_district"][:, district[unseen_area]] + draws[
            "tau_area"
        ][:, None] * rng.standard_normal((n_draws, int(unseen_area.sum())))
    unseen_all = (~seen) & (district < 0)
    if unseen_all.any():
        alpha[:, unseen_all] = draws["mu_city"][:, None]

    mu = alpha + draws["beta"] @ x.T
    if parcel is not None and "u_parcel" in draws:
        # known repeat parcel: use its learned effect (the repeat-sales win);
        # unseen/singleton parcel: marginalize the unknown house quality as
        # tau_parcel noise, which honestly widens its interval
        u = np.zeros((n_draws, n_rows))
        known = parcel >= 0
        u[:, known] = draws["u_parcel"][:, parcel[known]]
        unknown = ~known
        if unknown.any():
            u[:, unknown] = draws["tau_parcel"][:, None] * rng.standard_normal(
                (n_draws, int(unknown.sum()))
            )
        mu = mu + u
    if basis is not None and "w_spatial" in draws:
        mu = mu + (draws["tau_gp"][:, None] * draws["w_spatial"]) @ basis.T
    log_sigma = draws["g0"][:, None] + draws["g"] @ z_sigma.T
    if "u_sigma_district" in draws:
        u = np.zeros((n_draws, n_rows))
        known = district >= 0
        u[:, known] = draws["u_sigma_district"][:, district[known]]
        unknown = ~known
        if unknown.any():
            u[:, unknown] = draws["tau_sigma_district"][:, None] * rng.standard_normal(
                (n_draws, int(unknown.sum()))
            )
        log_sigma = log_sigma + u
    t_noise = rng.standard_t(np.maximum(draws["nu"], 2.1)[:, None], size=mu.shape)
    log_pred = mu + np.exp(log_sigma) * t_noise
    if time_adj_log is not None:
        log_pred = log_pred - time_adj_log[None, :]
    return np.asarray(np.exp(log_pred), dtype=np.float64)


def load_run(
    run_dir: Path,
) -> tuple[
    dict[str, np.ndarray], CovariateEncoder, GeoIndex, RBFBasis | None, ParcelIndex | None
]:
    """Load a trained run's posterior draws, encoder, geography, and (optional)
    spatial basis and parcel index."""
    with np.load(run_dir / "posterior_draws.npz") as data:
        draws = {name: data[name] for name in data.files}
    cov = json.loads((run_dir / "covariates.json").read_text())
    encoder = CovariateEncoder(
        names=cov["names"], medians=cov["medians"], means=cov["means"], stds=cov["stds"]
    )
    g = json.loads((run_dir / "geography.json").read_text())
    geo = GeoIndex(
        coarse=g["coarse"], fine=g["fine"], fine_to_coarse_ix=np.array(g["fine_to_coarse_ix"])
    )
    basis = None
    if (run_dir / "rbf.json").exists():
        r = json.loads((run_dir / "rbf.json").read_text())
        basis = RBFBasis(centers=np.array(r["centers"]), bandwidth_m=r["bandwidth_m"])
    parcels = None
    if (run_dir / "parcels.json").exists():
        p = json.loads((run_dir / "parcels.json").read_text())
        parcels = ParcelIndex(parcels=p["parcels"], min_sales=p["min_sales"])
    return draws, encoder, geo, basis, parcels


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
    time_adjusted: bool = True,
    nu_fixed: float | None = 8.0,
    spatial_basis: bool = False,
    parcel_effect: bool = False,
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
        "bayesian v2: %s train / %s test rows, %d draws x %d chains, time_adjusted=%s",
        f"{train_df.height:,}",
        f"{test_df.height:,}",
        draws,
        chains,
        time_adjusted,
    )

    encoder = CovariateEncoder.fit(train_df)
    geo = GeoIndex.fit(train_df)
    rbf = RBFBasis.fit(_xy(train_df), seed=seed) if spatial_basis else None
    # opt-in per-parcel latent quality. Measured 2026-07-04: adds ~nothing over
    # the mkt_parcel_prev_log_price_ref covariate (COD 30.43->30.37, width
    # 1.324->1.340) because only ~7% of test sales are train-repeat parcels and
    # only 3,806 parcels have 3+ sales where the effect beats "last price".
    parcels = ParcelIndex.fit(train_df) if parcel_effect else None

    def target(frame: pl.DataFrame) -> np.ndarray:
        y = np.log(frame["sale_price"].to_numpy())
        if time_adjusted:
            y = y + frame["time_adj_log"].to_numpy()
        return np.asarray(y, dtype=np.float64)

    x_train = encoder.transform(train_df)
    area_train, district_train = geo.indices(train_df)
    idata = _fit_posterior(
        x_train,
        rbf.transform(_xy(train_df)) if rbf is not None else None,
        _sigma_design(train_df),
        target(train_df),
        area_train,
        np.maximum(district_train, 0),
        geo,
        draws=draws,
        tune=tune,
        chains=chains,
        cores=cores,
        seed=seed,
        nu_fixed=nu_fixed,
        parcel_mapped=parcels.mapped(train_df) if parcels is not None else None,
        n_parcels=parcels.n if parcels is not None else 0,
    )

    posterior_draws = _thin_draws(idata, max_prediction_draws, seed, nu_fixed=nu_fixed)
    area_test, district_test = geo.indices(test_df)
    test_adj = (
        test_df["time_adj_log"].to_numpy() if time_adjusted else np.zeros(test_df.height)
    )
    price_draws = predict_price_draws(
        posterior_draws,
        encoder.transform(test_df),
        rbf.transform(_xy(test_df)) if rbf is not None else None,
        _sigma_design(test_df),
        area_test,
        district_test,
        seed=seed,
        time_adj_log=test_adj,
        parcel=parcels.seen(test_df) if parcels is not None else None,
    )
    point = np.median(price_draws, axis=0)
    pi_low = np.quantile(price_draws, PI_LOW, axis=0)
    pi_high = np.quantile(price_draws, PI_HIGH, axis=0)

    sale_price = test_df["sale_price"].to_numpy()
    covered = (sale_price >= pi_low) & (sale_price <= pi_high)

    from philly_assessments.models.baseline import _segments

    segments = _segments(test_df)
    district_counts = (
        test_df.group_by("loc_district").len().filter(pl.col("len") >= MIN_DISTRICT_SEGMENT_N)
    )
    for district in sorted(district_counts["loc_district"].drop_nulls().to_list()):
        segments.append(("district", district, test_df["loc_district"] == district))

    rows = []
    for segment_type, segment, mask in segments:
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
    for name in ("mu_city", "tau_district", "tau_area", "tau_gp", "tau_parcel", "g0",
                 "tau_sigma_district", "nu"):
        if name not in idata.posterior:
            continue
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
    g_flat = idata.posterior["g"].values.reshape(-1, len(SIGMA_TERM_NAMES))
    for i, name in enumerate(f"sigma_{term}" for term in SIGMA_TERM_NAMES):
        hyper_summary.append(
            {
                "parameter": name,
                "mean": float(g_flat[:, i].mean()),
                "sd": float(g_flat[:, i].std()),
                "q05": float(np.quantile(g_flat[:, i], 0.05)),
                "q95": float(np.quantile(g_flat[:, i], 0.95)),
            }
        )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-bayesian"
    run_dir = root / "models" / f"run_id={run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "params.json").write_text(
        json.dumps(
            {
                "model_version": 2,
                "draws": draws,
                "tune": tune,
                "chains": chains,
                "test_fraction": test_fraction,
                "time_adjusted": time_adjusted,
                "nu_fixed": nu_fixed,
                "spatial_basis": spatial_basis,
                "parcel_effect": parcel_effect,
                "n_parcel_effects": parcels.n if parcels is not None else 0,
                "sigma_terms": SIGMA_TERM_NAMES,
                "max_prediction_draws": max_prediction_draws,
                "seed": seed,
                "covariates": encoder.feature_names,
                "n_districts": len(geo.coarse),
                "n_areas": len(geo.fine),
                "n_rbf_centers": len(rbf.centers) if rbf is not None else 0,
                "rbf_bandwidth_m": rbf.bandwidth_m if rbf is not None else None,
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
    # cast: numpy's stubs match **kwds against the allow_pickle keyword
    np.savez_compressed(run_dir / "posterior_draws.npz", **cast(dict[str, Any], posterior_draws))
    (run_dir / "covariates.json").write_text(
        json.dumps(
            {
                "names": encoder.names,
                "medians": encoder.medians,
                "means": encoder.means,
                "stds": encoder.stds,
            },
            indent=2,
        )
        + "\n"
    )
    (run_dir / "geography.json").write_text(
        json.dumps(
            {
                "coarse": geo.coarse,
                "fine": geo.fine,
                "fine_to_coarse_ix": geo.fine_to_coarse_ix.tolist(),
            },
            indent=2,
        )
        + "\n"
    )
    if rbf is not None:
        (run_dir / "rbf.json").write_text(
            json.dumps(
                {"centers": rbf.centers.tolist(), "bandwidth_m": rbf.bandwidth_m}, indent=2
            )
            + "\n"
        )
    if parcels is not None:
        (run_dir / "parcels.json").write_text(
            json.dumps({"parcels": parcels.parcels, "min_sales": parcels.min_sales}) + "\n"
        )

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
