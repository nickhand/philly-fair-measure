from __future__ import annotations

import numpy as np
import polars as pl

from philly_fair_measure.models.risk import _risk_evaluation, score_prediction_risk


def test_risk_coverage_orders_error_without_dropping_estimates():
    actual = np.zeros(100)
    score = np.linspace(0.01, 1.0, 100)
    point = score.copy()
    table = _risk_evaluation(score, actual, point, elevated=0.75, high=0.90)
    tiers = {row["segment"]: row for row in table.filter(pl.col("view") == "tier").to_dicts()}
    assert tiers["standard"]["rmse_log"] < tiers["elevated"]["rmse_log"]
    assert tiers["elevated"]["rmse_log"] < tiers["high"]["rmse_log"]
    retained = table.filter(pl.col("view") == "risk_coverage").sort("retained_fraction")
    assert retained.height == 5
    assert retained["n"][-1] == 100
    assert retained["rmse_log"][0] < retained["rmse_log"][-1]


def test_risk_scoring_degrades_to_standard_without_artifact(tmp_path):
    score, tier = score_prediction_risk(tmp_path, pl.DataFrame({"parcel_id": ["a", "b"]}))
    assert score.tolist() == [0.0, 0.0]
    assert tier.tolist() == ["standard", "standard"]


def test_empty_risk_tier_is_reported_without_invalid_means():
    actual = np.zeros(10)
    point = np.zeros(10)
    score = np.zeros(10)
    table = _risk_evaluation(score, actual, point, elevated=0.0, high=0.0)
    standard = table.filter(pl.col("segment") == "standard").to_dicts()[0]
    assert standard["n"] == 0
    assert standard["mean_absolute_log_error"] is None
