from philly_assessments.diagnostics.stability import _summary


def test_summary_stats():
    s = _summary([25.0, 24.5, 25.9, 25.8, 25.6])
    assert s["folds"] == 5
    assert s["cod_min"] == 24.5
    assert s["cod_max"] == 25.9
    assert 25.0 < s["cod_mean"] < 25.5
    assert s["cod_sd"] > 0
