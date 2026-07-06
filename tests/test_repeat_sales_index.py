"""Repeat-sales index machinery: BMN curve recovery, area drift, adjustment math.

Synthetic ground truth — a known citywide appreciation path and a known
area-level drift — must be recovered by the estimators, and
`with_time_adjustment` must apply the drift with the documented sign
(a faster-appreciating area needs MORE adjustment for older sales).
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


def test_with_time_adjustment_applies_area_drift():
    months = [date(2020, 1, 1), date(2025, 1, 1)]
    index = pl.DataFrame(
        {
            "district": ["d_0", "d_0", CITYWIDE, CITYWIDE],
            "month": months * 2,
            "log_index": [-0.30, 0.0, -0.30, 0.0],
            "n_sales": [5, 5, 5, 5],
            "ref_month": [months[1]] * 4,
        }
    )
    drift = pl.DataFrame({"market_area": ["ma_hot"], "drift_per_yr": [0.04], "n_pairs": [50]})
    frame = pl.DataFrame(
        {
            "loc_district": ["d_0", "d_0"],
            "loc_market_area": ["ma_hot", "ma_cold"],
            "sale_date": [date(2020, 1, 1), date(2020, 1, 1)],
        }
    )
    out = with_time_adjustment(frame, index, area_drift=drift)
    # base adjustment 0.30; the hot area adds ~5 years x 0.04
    hot, cold = out["time_adj_log"].to_list()
    assert cold == pytest.approx(0.30)
    assert hot == pytest.approx(0.30 + 5.0 * 0.04, abs=0.01)
    # sales at the reference month get no drift regardless of area
    at_ref = with_time_adjustment(
        frame.with_columns(pl.lit(months[1]).alias("sale_date")), index, area_drift=drift
    )
    assert at_ref["time_adj_log"].to_list() == pytest.approx([0.0, 0.0])


def test_quarter_ix():
    dates = np.array(["2013-01-15", "2013-04-01", "2014-12-31"], dtype="datetime64[D]")
    assert _quarter_ix(dates, 2013).tolist() == [0, 1, 7]
