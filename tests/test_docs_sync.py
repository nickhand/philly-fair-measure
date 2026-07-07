"""docs_sync: the generated blocks render from stats, sync is idempotent,
and --check catches drift without touching files."""

import json
from pathlib import Path

from philly_fair_measure.docs_sync import (
    STATS_PATH,
    condo_bullet,
    model_md_results_table,
    readme_results_tables,
    readme_screen_counts,
    sync_docs,
    veq_card_full,
    veq_card_iaao,
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
    "condo_card": {
        "model": {
            "rmse_log": 0.243,
            "cod": 17.5,
            "median_ratio": 1.053,
            "prd": 1.06,
            "prb": -0.042,
            "mape_pct": 19.2,
        },
        "opa": {
            "rmse_log": 0.278,
            "cod": 18.8,
            "median_ratio": 0.915,
            "prd": 1.03,
            "prb": -0.001,
            "mape_pct": 18.9,
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


def test_veq_and_condo_builders_render_with_pass_marks():
    iaao = veq_card_iaao(STATS)
    # model passes both vertical-equity tests, sits marginal on COD; OPA fails
    assert "| PRB | ±0.05 | -0.058 ✗ | +0.010 ✓ |" in iaao
    assert "| COD | ≤ 15 | 24.7 ✗ | 19.3 ⚠︎ |" in iaao
    full = veq_card_full(STATS)
    assert "| MAPE | n/a | 34.0% | 26.4% |" in full  # full card carries a MAPE row
    condo = condo_bullet(STATS)
    assert "rmse 0.243 vs 0.278" in condo and "COD 17.5 vs 18.8" in condo


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
        "<!-- generated:model-results-table:end -->\n\n"
        "<!-- generated:condo-card:begin -->\n<!-- generated:condo-card:end -->\n"
    )
    (tmp_path / "docs" / "vertical-equity-report-card.md").write_text(
        "# card\n\n"
        "<!-- generated:veq-meta:begin -->\n<!-- generated:veq-meta:end -->\n\n"
        "<!-- generated:veq-card-iaao:begin -->\n<!-- generated:veq-card-iaao:end -->\n\n"
        "<!-- generated:veq-card-full:begin -->\n<!-- generated:veq-card-full:end -->\n"
    )
    return tmp_path


def test_sync_rewrites_then_is_idempotent_and_check_passes(tmp_path):
    root = _repo(tmp_path)
    first = sync_docs(root)
    assert set(first.changed) == {
        "README.md:readme-screen-counts",
        "docs/model.md:model-results-table",
        "docs/model.md:condo-card",
        "docs/vertical-equity-report-card.md:veq-meta",
        "docs/vertical-equity-report-card.md:veq-card-iaao",
        "docs/vertical-equity-report-card.md:veq-card-full",
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
