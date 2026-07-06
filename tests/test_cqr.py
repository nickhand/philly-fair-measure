"""CQR math: conformity scores and the finite-sample corrections.

The full bake-off (`fair-measure cqr-check`) needs trained runs and the mart;
these tests pin the statistical machinery itself on synthetic data, including
the coverage guarantee the correction exists to provide.
"""

import numpy as np

from philly_fair_measure.models.cqr import _global_correction, _knn_correction, cqr_score


def test_cqr_score_signs():
    y = np.array([0.0, 5.0, 10.0])
    lo = np.array([2.0, 2.0, 2.0])
    hi = np.array([8.0, 8.0, 8.0])
    s = cqr_score(y, lo, hi)
    # below the band: distance to lo; inside: negative; above: distance to hi
    assert s[0] == 2.0
    assert s[1] == -3.0
    assert s[2] == 2.0


def test_global_correction_gives_finite_sample_coverage():
    rng = np.random.default_rng(7)
    n_cal, n_test, alpha = 2000, 4000, 0.10
    # heteroscedastic truth the (deliberately misspecified) bands miss
    y_cal = rng.normal(0, 1 + (rng.random(n_cal) > 0.5), n_cal)
    q = np.full(n_cal, 0.8)
    scores = cqr_score(y_cal, -q, q)
    corr = _global_correction(scores, alpha)
    y_test = rng.normal(0, 1 + (rng.random(n_test) > 0.5), n_test)
    covered = (y_test >= -0.8 - corr) & (y_test <= 0.8 + corr)
    assert covered.mean() >= 1 - alpha - 0.02  # finite-sample guarantee, small slack


def test_knn_correction_adapts_locally():
    rng = np.random.default_rng(11)
    n = 3000
    # two spatial clusters: quiet west (sd 0.2), noisy east (sd 1.5)
    east = rng.random(n) > 0.5
    xy = np.column_stack(
        [np.where(east, 10_000.0, 0.0) + rng.normal(0, 50, n), rng.normal(0, 50, n)]
    )
    y = rng.normal(0, np.where(east, 1.5, 0.2), n)
    scores = cqr_score(y, np.full(n, -0.1), np.full(n, 0.1))
    targets = np.array([[0.0, 0.0], [10_000.0, 0.0]])
    corr = _knn_correction(scores, xy, targets, alpha=0.10, k=200)
    assert corr[1] > corr[0] * 2  # the noisy cluster needs a far larger correction


def test_knn_correction_falls_back_without_coordinates():
    scores = np.array([0.1, 0.2, 0.3, 0.4])
    xy = np.full((4, 2), np.nan)
    corr = _knn_correction(scores, xy, np.array([[np.nan, np.nan]]), alpha=0.5, k=2)
    assert np.isfinite(corr[0])
    assert corr[0] == _global_correction(scores, 0.5)
