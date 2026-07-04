import numpy as np
import polars as pl
import pytest

from philly_assessments.diagnostics.fairness_robustness import _by_race


def test_by_race_median_ratio_and_min_group():
    rng = np.random.default_rng(0)
    n = 1200
    groups = np.array(["White alone", "Black alone", "tiny"] * (n // 3))
    df = pl.DataFrame({"acs_majority_race": groups})
    price = rng.uniform(100_000, 300_000, n)
    # value = 1.0x price for White, 1.1x for Black (a planted 10% level gap)
    value = np.where(groups == "Black alone", price * 1.1, price)
    out = _by_race(df, value, price)
    assert "White alone" in out and "Black alone" in out
    assert out["White alone"].median_ratio == pytest.approx(1.0, abs=0.01)
    assert out["Black alone"].median_ratio == pytest.approx(1.1, abs=0.01)
    # groups below the 300-row floor are dropped ("tiny" has 400 -> kept;
    # make a truly tiny one)
    small = pl.DataFrame({"acs_majority_race": ["Hispanic/Latino, any race"] * 100})
    out2 = _by_race(small, np.ones(100), np.ones(100))
    assert out2 == {}
