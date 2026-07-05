from datetime import datetime

import polars as pl
import pytest

from philly_assessments.features.spatial import knn_ppsf_at_date, knn_ppsf_for_sales


def _point(sale_id, parcel, x, y, date, value):
    return {
        "sale_id": sale_id,
        "parcel_id": parcel,
        "x_m": float(x),
        "y_m": float(y),
        "sale_date": date,
        "adj_log_ppsf": float(value),
    }


def test_knn_for_sales_uses_only_prior_quarters_and_other_parcels():
    points = pl.DataFrame(
        [
            _point("a", "p1", 0, 0, datetime(2020, 1, 15), 5.0),
            # same quarter as `a`: must NOT see `a` (quarter blocking)
            _point("b", "p2", 10, 0, datetime(2020, 2, 15), 6.0),
            # later quarter: sees both a and b
            _point("c", "p3", 5, 0, datetime(2020, 5, 15), 7.0),
            # later still, SAME PARCEL as `a`: sees b and c but never its own parcel
            _point("d", "p1", 0, 5, datetime(2021, 2, 15), 8.0),
        ]
    )
    out = {row["sale_id"]: row for row in knn_ppsf_for_sales(points, k=15).to_dicts()}

    assert out["a"]["mkt_knn_n"] == 0
    assert out["a"]["mkt_knn_log_ppsf"] is None
    assert out["b"]["mkt_knn_n"] == 0  # `a` is in the same quarter — excluded

    assert out["c"]["mkt_knn_n"] == 2  # a and b
    # distance-weighted: a at 5m (w=1/105), b at 5m (w=1/105) -> plain mean
    assert out["c"]["mkt_knn_log_ppsf"] == pytest.approx((5.0 + 6.0) / 2)

    assert out["d"]["mkt_knn_n"] == 2  # b and c; own parcel `a` excluded
    w_b = 1.0 / ((10**2 + 5**2) ** 0.5 + 100.0)
    w_c = 1.0 / ((5**2 + 5**2) ** 0.5 + 100.0)
    expected = (w_b * 6.0 + w_c * 7.0) / (w_b + w_c)
    assert out["d"]["mkt_knn_log_ppsf"] == pytest.approx(expected)


def test_knn_at_date_windows_and_excludes_own_parcel():
    points = pl.DataFrame(
        [
            _point("s1", "p1", 0, 0, datetime(2024, 1, 1), 5.0),
            _point("s2", "p2", 10, 0, datetime(2025, 1, 1), 6.0),
            _point("s3", "p3", 20, 0, datetime(2015, 1, 1), 9.0),  # outside 5y window
            _point("s4", "p4", 30, 0, datetime(2026, 8, 1), 9.0),  # after valuation date
        ]
    )
    targets = pl.DataFrame({"parcel_id": ["p1", "p9"], "x_m": [0.0, 5.0], "y_m": [0.0, 0.0]})
    out = {
        row["parcel_id"]: row
        for row in knn_ppsf_at_date(points, targets, datetime(2026, 7, 1), k=15).to_dicts()
    }
    # p1 excludes its own sale: only s2 remains in-window
    assert out["p1"]["mkt_knn_n"] == 1
    assert out["p1"]["mkt_knn_log_ppsf"] == pytest.approx(6.0)
    # p9 sees s1 and s2 (s3 too old, s4 in the future)
    assert out["p9"]["mkt_knn_n"] == 2
