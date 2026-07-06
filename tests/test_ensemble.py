import numpy as np

from philly_fair_measure.models.ensemble import _interval_row, stack_weight


def test_stack_weight_recovers_true_blend():
    rng = np.random.default_rng(0)
    a = rng.normal(12.0, 1.0, 5000)
    b = a + rng.normal(0.0, 0.5, 5000)
    y = 0.7 * a + 0.3 * b + rng.normal(0.0, 0.01, 5000)
    assert abs(stack_weight(a, b, y) - 0.7) < 0.02


def test_stack_weight_clips_to_convex_blend():
    rng = np.random.default_rng(1)
    a = rng.normal(12.0, 1.0, 1000)
    b = a + rng.normal(0.0, 0.5, 1000)
    # y beyond a in the a-b direction: unclipped least squares would want w > 1
    assert stack_weight(a, b, 2 * a - b) == 1.0
    assert stack_weight(a, b, 2 * b - a) == 0.0


def test_stack_weight_identical_arms_falls_back():
    a = np.full(10, 12.0)
    assert stack_weight(a, a.copy(), a + 0.1) == 0.5


def test_interval_row_coverage_and_width():
    y = np.array([100.0, 200.0, 300.0])
    lo = np.array([90.0, 210.0, 250.0])  # misses the middle one
    hi = np.array([110.0, 260.0, 350.0])
    row = _interval_row("x", lo, hi, y)
    assert row["coverage"] == 2 / 3
    assert row["median_width_ratio"] == np.median(hi / lo)
