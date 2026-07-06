import numpy as np

from philly_fair_measure.diagnostics.historical_redistribution import _tier_redistribution


def test_uniform_assessment_is_neutral():
    rng = np.random.default_rng(0)
    value = rng.uniform(50_000, 500_000, 1000)
    opa = 0.9 * value  # every home at the same ratio -> no redistribution
    bottom, q1q5, med = _tier_redistribution(opa, value)
    assert abs(bottom) < 1e-9
    assert abs(q1q5 - 1.0) < 1e-9
    assert abs(med - 0.9) < 1e-9


def test_flat_assessment_is_regressive():
    value = np.linspace(50_000, 500_000, 1000)
    opa = np.full(1000, 200_000.0)  # everyone assessed the same -> steeply regressive
    bottom, q1q5, med = _tier_redistribution(opa, value)
    assert bottom > 0  # the cheap bottom overpays
    assert q1q5 > 1.0  # q1 ratio exceeds q5 ratio (the definition of regressive)
