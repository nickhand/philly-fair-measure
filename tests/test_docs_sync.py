"""docs_sync: the generated blocks render from stats, sync is idempotent,
and --check catches drift without touching files."""

import json
from pathlib import Path

from philly_fair_measure.docs_sync import (
    STATS_PATH,
    model_md_results_table,
    readme_results_tables,
    readme_screen_counts,
    sync_docs,
)

STATS = {
    "meta": {"model_run_id": "20990101T000000Z-baseline", "n_test": 19_484},
    "iaao_card": {
        "model": {"median_ratio": 1.001, "cod": 19.3, "prd": 1.024, "prb": 0.01, "mape_pct": 19.3},
        "opa": {"median_ratio": 0.848, "cod": 24.7, "prd": 1.07, "prb": -0.058, "mape_pct": 24.9},
    },
    "full_card": {
        "model": {
            "median_ratio": 1.031,
            "cod": 25.5,
            "prd": 1.087,
            "prb": -0.073,
            "mape_pct": 26.4,
        },
        "opa": {"median_ratio": 0.983, "cod": 34.5, "prd": 1.19, "prb": -0.234, "mape_pct": 34.0},
    },
    "screen": {
        "properties": 496_975,
        "over": 1_643,
        "under": 6_253,
        "watch": 44_408,
        "insufficient": 93,
    },
    "results_table": {
        "lightgbm": {
            "rmse_log": 0.333,
            "mape_pct": 26.4,
            "median_ratio": 1.031,
            "cod": 25.5,
            "prd": 1.087,
            "prb": -0.073,
            "mki": 0.905,
        },
        "ridge": {
            "rmse_log": 0.427,
            "mape_pct": 37.4,
            "median_ratio": 1.045,
            "cod": 35.5,
            "prd": 1.061,
            "prb": -0.08,
            "mki": 0.981,
        },
        "opa_assessment": {
            "rmse_log": 0.449,
            "mape_pct": 34.0,
            "median_ratio": 0.983,
            "cod": 34.5,
            "prd": 1.19,
            "prb": -0.234,
            "mki": 0.787,
        },
    },
}


def test_builders_render_the_numbers():
    counts = readme_screen_counts(STATS)
    assert "**496,975**" in counts and "**1,643**" in counts and "93 records" in counts
    tables = readme_results_tables(STATS)
    assert "`20990101T000000Z-baseline`" in tables
    assert "| This model | 1.001 | 19.3 | 1.024 | +0.010 | 19.3% |" in tables
    model_table = model_md_results_table(STATS)
    assert "| **LightGBM** | **0.333** | **26.4%** | 1.031" in model_table
    assert "| Ridge | 0.427 |" in model_table


def _repo(tmp_path: Path) -> Path:
    (tmp_path / STATS_PATH).parent.mkdir(parents=True)
    (tmp_path / STATS_PATH).write_text(json.dumps(STATS))
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "# Title\n\nprose stays\n\n"
        "<!-- generated:readme-screen-counts:begin -->\nstale\n"
        "<!-- generated:readme-screen-counts:end -->\n\nmore prose\n"
    )
    (tmp_path / "docs" / "model.md").write_text(
        "## 6. Results\n\n"
        "<!-- generated:model-results-table:begin -->\n"
        "<!-- generated:model-results-table:end -->\n"
    )
    return tmp_path


def test_sync_rewrites_then_is_idempotent_and_check_passes(tmp_path):
    root = _repo(tmp_path)
    first = sync_docs(root)
    assert set(first.changed) == {
        "README.md:readme-screen-counts",
        "docs/model.md:model-results-table",
    }
    readme = (root / "README.md").read_text()
    assert "**496,975**" in readme and "stale" not in readme
    assert "prose stays" in readme and "more prose" in readme  # untouched outside markers
    # idempotent; --check clean
    assert sync_docs(root).changed == []
    assert sync_docs(root, check=True).changed == []


def test_check_detects_drift_without_writing(tmp_path):
    root = _repo(tmp_path)
    sync_docs(root)
    hand_edited = (root / "README.md").read_text().replace("496,975", "999,999")
    (root / "README.md").write_text(hand_edited)
    result = sync_docs(root, check=True)
    assert result.changed == ["README.md:readme-screen-counts"]
    assert "999,999" in (root / "README.md").read_text()  # check mode never writes
