"""equity_robustness: neighborhood binning separates a mis-priced individual
sale from genuine neighborhood-level bias (the Doucet diagnostic)."""

import numpy as np
import polars as pl

from philly_fair_measure.diagnostics.equity_robustness import (
    morans_i,
    neighborhood_levels,
    q1q5_medians,
)


def test_artifact_sales_inflate_individual_bin_but_not_neighborhood_bin():
    # A cheap neighborhood (level 100k) with 20 accurately assessed sales, and
    # a rich one (level 500k) with 60 accurate sales plus 20 mis-validated
    # bargains: worth (and assessed near) 450k but recorded selling for 100k,
    # ratio 4.5. Binned by their own price the bargains crowd into the bottom
    # quintile with the genuinely cheap homes and drag its median ratio up;
    # binned by their neighborhood's level they return to the top tier.
    price = np.array([100_000.0] * 20 + [500_000.0] * 60 + [100_000.0] * 20)
    ratio = np.array([1.0] * 80 + [4.5] * 20)
    nbhd_level = np.array([100_000.0] * 20 + [500_000.0] * 80)

    q1_ind, q5_ind, *_ = q1q5_medians(price, ratio)
    q1_nbhd, q5_nbhd, *_ = q1q5_medians(nbhd_level, ratio)

    assert q1_ind > 1.5  # the illusion: "cheap homes are over-assessed"
    assert q1_nbhd == 1.0 and q5_nbhd == 1.0  # the artifact-robust view: flat
    assert q5_ind == 1.0


def test_neighborhood_levels_threshold_and_time_adjustment():
    sf = pl.DataFrame(
        {
            "loc_market_area": ["big"] * 60 + ["thin"] * 5 + [None] * 3,
            "sale_price": [100_000.0] * 68,
            # the big area's sales carry +0.7 log of index appreciation: its
            # level must read ~2x the raw price, not the stale nominal one
            "time_adj_log": [0.7] * 60 + [0.0] * 8,
        }
    )
    levels = neighborhood_levels(sf, min_sales=50)
    assert levels.height == 1  # thin area (5 sales) and null areas are dropped
    row = levels.to_dicts()[0]
    assert row["loc_market_area"] == "big" and row["nbhd_n"] == 60
    assert abs(row["nbhd_level"] - 100_000 * np.exp(0.7)) < 1.0


def test_morans_i_detects_clustered_vs_random_errors():
    rng = np.random.default_rng(7)
    lon = rng.uniform(-75.2, -75.0, 400)
    lat = rng.uniform(39.9, 40.1, 400)
    clustered = np.where(lon < -75.1, 0.3, -0.3) + rng.normal(0, 0.05, 400)
    random = rng.normal(0, 0.3, 400)
    assert morans_i(lon, lat, clustered) > 0.5
    assert abs(morans_i(lon, lat, random)) < 0.15
