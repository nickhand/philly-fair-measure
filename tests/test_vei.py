"""Vertical Equity Indicator, validated against the IAAO 2025 Standard on
Ratio Studies exposure draft: Table 1 (the 54-sale example dataset) must
reproduce Table 4 (per-quartile medians, proxies, and 90% CIs), the VEI point
estimate of 50.12%, and the VEI significance of 17.51% (§8.2.1.2)."""

import numpy as np
import pytest

from philly_fair_measure.models.metrics import vertical_equity_indicator

# IAAO exposure draft Table 1: (assessed value, sale price), observations 1-54.
TABLE_1 = [
    (240_000, 690_000),
    (144_000, 296_250),
    (392_000, 787_500),
    (199_200, 372_000),
    (340_800, 574_500),
    (472_000, 795_000),
    (336_000, 559_500),
    (284_800, 465_000),
    (436_000, 693_600),
    (191_200, 298_500),
    (225_000, 350_000),
    (194_000, 295_000),
    (481_600, 732_000),
    (338_400, 495_000),
    (164_800, 237_000),
    (252_800, 352_500),
    (945_000, 1_289_000),
    (280_000, 379_000),
    (407_000, 540_000),
    (423_000, 560_000),
    (306_800, 390_000),
    (236_800, 300_000),
    (361_000, 450_000),
    (290_400, 345_000),
    (235_200, 277_500),
    (415_000, 485_000),
    (381_000, 442_000),
    (380_000, 435_000),
    (875_000, 998_000),
    (680_000, 772_500),
    (329_000, 365_000),
    (457_000, 487_000),
    (516_000, 547_500),
    (295_200, 300_000),
    (580_000, 580_000),
    (840_000, 840_000),
    (640_000, 622_500),
    (660_000, 637_500),
    (354_000, 340_000),
    (800_000, 750_000),
    (390_000, 352_500),
    (800_000, 705_000),
    (469_000, 410_000),
    (1_000_000, 859_500),
    (920_000, 787_500),
    (527_000, 440_000),
    (800_000, 648_000),
    (786_000, 630_000),
    (496_000, 388_500),
    (1_000_000, 765_000),
    (320_000, 243_750),
    (960_000, 720_000),
    (952_000, 705_000),
    (327_200, 240_000),
]
AV = np.array([av for av, _ in TABLE_1], dtype=float)
SP = np.array([sp for _, sp in TABLE_1], dtype=float)


def test_reproduces_the_standards_worked_example():
    r = vertical_equity_indicator(AV, SP)
    assert r.n == 54 and r.n_groups == 4
    # Table 4: group sizes, median proxies, median ratios, 90% CIs
    assert [g.n for g in r.groups] == [14, 13, 14, 13]
    for got, want in zip(
        [g.median_proxy for g in r.groups], [302_709, 436_450, 584_538, 903_995], strict=True
    ):
        assert got == pytest.approx(want, abs=1.0)
    for got, want in zip(
        [g.median_ratio for g in r.groups], [0.728, 0.862, 0.755, 1.163], strict=True
    ):
        assert got == pytest.approx(want, abs=0.001)
    assert r.groups[0].ci_low == pytest.approx(0.643, abs=0.001)
    assert r.groups[0].ci_high == pytest.approx(0.848, abs=0.001)
    assert r.groups[1].ci_low == pytest.approx(0.787, abs=0.001)
    assert r.groups[1].ci_high == pytest.approx(1.041, abs=0.001)
    assert r.groups[2].ci_low == pytest.approx(0.594, abs=0.001)
    assert r.groups[2].ci_high == pytest.approx(1.000, abs=0.001)
    assert r.groups[3].ci_low == pytest.approx(1.000, abs=0.001)
    assert r.groups[3].ci_high == pytest.approx(1.248, abs=0.001)
    # §8.2.1.2: VEI 50.12%, significance 17.51% (their arithmetic uses the
    # 3-decimal displayed medians; full precision lands within a quarter point)
    assert r.vei == pytest.approx(50.12, abs=0.25)
    assert r.significance == pytest.approx(17.51, abs=0.25)
    assert r.verdict == "unacceptable"


def test_group_count_follows_the_sample_size_rules():
    rng = np.random.default_rng(3)
    for n, expected in [(20, 2), (50, 2), (51, 4), (500, 4), (501, 10), (5000, 10)]:
        sp = rng.uniform(100_000, 900_000, n)
        av = sp * rng.normal(1.0, 0.05, n)
        assert vertical_equity_indicator(av, sp).n_groups == expected
    assert vertical_equity_indicator(AV[:19], SP[:19]).verdict == "insufficient_sample"


def test_flat_assessments_are_acceptable():
    rng = np.random.default_rng(11)
    sp = rng.uniform(50_000, 1_000_000, 800)
    av = sp * rng.normal(1.0, 0.08, 800)
    r = vertical_equity_indicator(av, sp)
    assert r.verdict == "acceptable" and abs(r.vei) < 10


def test_within_band_point_estimate_needs_no_significance_test():
    # a mild 6% tilt: |VEI| <= 10 is acceptable outright, significance unset
    rng = np.random.default_rng(5)
    sp = np.sort(rng.uniform(100_000, 1_000_000, 600))
    tilt = np.linspace(0.97, 1.03, 600)
    av = sp * tilt * rng.normal(1.0, 0.01, 600)
    r = vertical_equity_indicator(av, sp)
    assert abs(r.vei) <= 10 and r.verdict == "acceptable" and r.significance is None
