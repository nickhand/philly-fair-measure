"""Repeat-sales index machinery: BMN curve recovery, geo fallback, adjustment math.

Synthetic ground truth — a known appreciation path per geography — must be
recovered by the estimators, and `with_time_adjustment` must pick the most
specific curve a row carries (market area → district → citywide), so a
sub-area that lagged its district carries its older sales forward by LESS
(the 2314 Wallace St fix).
"""

from datetime import date

import numpy as np
import polars as pl
import pytest

from philly_fair_measure.features.price_index import (
    CITYWIDE,
    _bmn_curve,
    _quarter_ix,
    _repeat_pairs,
    with_time_adjustment,
)


def test_bmn_curve_recovers_known_appreciation():
    rng = np.random.default_rng(3)
    n_quarters = 20
    truth = np.linspace(0.0, 0.4, n_quarters)  # steady +40% log over 5 years
    q1 = rng.integers(0, n_quarters - 4, 800)
    q2 = q1 + rng.integers(2, 4, 800)
    dlog = truth[q2] - truth[q1] + rng.normal(0, 0.05, 800)
    curve = _bmn_curve(q1, q2, dlog, n_quarters, prior=None)
    # anchored at 0, tracks the truth within noise
    assert curve[0] == 0.0
    assert np.abs(curve - truth).max() < 0.05


def test_bmn_ridge_pulls_thin_district_toward_prior():
    prior = np.linspace(0.0, 0.4, 20)
    # three noisy pairs cannot support 19 free parameters — the ridge keeps
    # the curve glued to the citywide prior instead of exploding
    q1 = np.array([0, 2, 5])
    q2 = np.array([8, 10, 15])
    dlog = np.array([0.9, -0.5, 1.2])
    curve = _bmn_curve(q1, q2, dlog, 20, prior=prior)
    assert np.abs(curve - prior).max() < 0.2


def test_repeat_pairs_hygiene():
    sales = pl.LazyFrame(
        {
            "parcel_id": ["a", "a", "b", "b", "c", "c"],
            "sale_date": [
                date(2015, 1, 1),
                date(2020, 1, 1),  # a: clean 5y pair
                date(2019, 1, 1),
                date(2019, 3, 1),  # b: held 2 months — dropped
                date(2018, 1, 1),
                date(2020, 1, 1),  # c: doubled in 2y (flip) — dropped
            ],
            "sale_price": [200_000.0, 260_000.0, 100_000.0, 150_000.0, 100_000.0, 250_000.0],
            "validity_status": ["arms_length"] * 6,
        }
    )
    pairs = _repeat_pairs(sales)
    assert pairs["parcel_id"].to_list() == ["a"]
    assert pairs["held_yrs"][0] == pytest.approx(5.0, abs=0.05)


def test_with_time_adjustment_prefers_area_then_district_then_city():
    months = [date(2020, 1, 1), date(2025, 1, 1)]
    # d_0 climbed +0.30 over the window; ma_lag (a sub-area) only +0.10 — it
    # plateaued, the Wallace case. ma_hot has no curve of its own; the last
    # row has neither district nor area and must reach the citywide fallback.
    index = pl.DataFrame(
        {
            "district": ["d_0", "d_0", "ma_lag", "ma_lag", CITYWIDE, CITYWIDE],
            "month": months * 3,
            "log_index": [-0.30, 0.0, -0.10, 0.0, -0.25, 0.0],
            "n_sales": [5] * 6,
            "ref_month": [months[1]] * 6,
        }
    )
    frame = pl.DataFrame(
        {
            "loc_district": ["d_0", "d_0", None],
            "loc_market_area": ["ma_lag", "ma_hot", None],
            "sale_date": [date(2020, 1, 1)] * 3,
        }
    )
    lag, hot, orphan = with_time_adjustment(frame, index)["time_adj_log"].to_list()
    # ma_lag has its own curve — only +0.10 to reach reference-month dollars,
    # NOT the district's +0.30 (the over-adjustment the area level removes)
    assert lag == pytest.approx(0.10)
    assert hot == pytest.approx(0.30)  # no area curve -> district
    assert orphan == pytest.approx(0.25)  # no district -> citywide
    # a frame without the area column at all falls back to the district cleanly
    no_area = with_time_adjustment(frame.drop("loc_market_area"), index)
    assert no_area["time_adj_log"].to_list() == pytest.approx([0.30, 0.30, 0.25])
    # sales at the reference month need no adjustment in any geography
    at_ref = with_time_adjustment(frame.with_columns(pl.lit(months[1]).alias("sale_date")), index)
    assert at_ref["time_adj_log"].to_list() == pytest.approx([0.0, 0.0, 0.0])


def test_quarter_ix():
    dates = np.array(["2013-01-15", "2013-04-01", "2014-12-31"], dtype="datetime64[D]")
    assert _quarter_ix(dates, 2013).tolist() == [0, 1, 7]
