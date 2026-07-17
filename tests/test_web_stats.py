"""Web-stat export configuration and annual-report verdict contract."""

import json
from pathlib import Path

import pytest

from philly_fair_measure.web_stats import _benchmark_validation, load_annual_report_settings


def test_committed_annual_report_settings_are_complete() -> None:
    settings = load_annual_report_settings(Path("annual_report.json"))

    assert settings["tax_year"] == 2027
    assert settings["comparison_year"] == 2026
    assert settings["status"] == "provisional"
    assert settings["appeal_deadlines"] == {
        "first_level_review": "2026-09-01",
        "formal_appeal": "2026-10-05",
    }
    assert set(settings["sources"]) == {
        "opa_methodology_url",
        "opa_ratio_studies_url",
        "iaao_ratio_study_url",
        "notebook_url",
    }


def test_annual_report_settings_reject_a_mismatched_effective_year(tmp_path: Path) -> None:
    settings = load_annual_report_settings(Path("annual_report.json"))
    settings["effective_date"] = "2028-01-01"
    path = tmp_path / "annual_report.json"
    path.write_text(json.dumps(settings))

    with pytest.raises(ValueError, match="effective_date must fall in tax_year"):
        load_annual_report_settings(path)


def test_benchmark_validation_does_not_hide_mixed_results() -> None:
    card = {
        "model": {"prd": 1.02, "prb": 0.08, "vei": 2.0},
        "opa": {"prd": 1.06, "prb": 0.04, "vei": 10.0},
    }

    result = _benchmark_validation(card)

    assert result["metric_directions"] == {
        "prd": "model_fairer",
        "prb": "opa_fairer",
        "vei": "model_fairer",
    }
    assert result["verdict"] == "mixed"
