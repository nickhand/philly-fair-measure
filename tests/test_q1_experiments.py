from datetime import date

import numpy as np
import polars as pl

from philly_fair_measure.diagnostics.q1_experiments import (
    repeat_recovery_labels,
    smooth_low_value_weight,
)


def test_repeat_recovery_labels_require_confirmed_future_sale():
    frame = pl.DataFrame(
        {
            "sale_id": ["a1", "a2", "b1", "b2", "c1", "c2"],
            "parcel_id": ["a", "a", "b", "b", "c", "c"],
            "sale_date": [
                date(2020, 1, 1),
                date(2021, 1, 1),
                date(2020, 1, 1),
                date(2021, 1, 1),
                date(2021, 1, 1),
                date(2022, 1, 1),
            ],
            "sale_price": [100_000.0, 180_000.0, 100_000.0, 110_000.0, 100_000.0, 200_000.0],
            "time_adj_log": [0.0] * 6,
            "evt_n_completed_reno_permits_5y_before": [0, 2, 0, 0, 0, 2],
        }
    )
    labels = repeat_recovery_labels(frame, confirmation_cutoff=date(2021, 6, 1))
    by_id = {row["sale_id"]: row for row in labels.to_dicts()}
    assert by_id["a1"]["weak_recovery_label"] == 1
    assert by_id["b1"]["weak_recovery_label"] == 0
    assert "c1" not in by_id  # confirming resale is after the cutoff


def test_smooth_low_value_router_is_bounded_and_monotone():
    value = np.array([9.0, 10.0, 11.0])
    weight = smooth_low_value_weight(value, center=10.0, scale=0.2)
    assert np.all((weight >= 0.0) & (weight <= 1.0))
    assert weight[0] > weight[1] > weight[2]
    assert weight[1] == 0.5
