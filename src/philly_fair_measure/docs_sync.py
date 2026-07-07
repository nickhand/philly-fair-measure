"""Sync generated number blocks in the docs from the committed stats JSON.

README.md and docs/model.md quote screen counts and results tables that
change on every retrain. Hand-editing them drifted three times in one day
(2026-07-06); this module makes the numbers mechanical:

- `web/src/data/siteStats.json` is the single committed source (written by
  `fair-measure export-web-stats`, which reads the run artifacts and marts).
- Regions between ``<!-- generated:<name>:begin -->`` and
  ``<!-- generated:<name>:end -->`` markers are rewritten verbatim from it by
  `fair-measure sync-docs`. Everything outside markers is hand-written prose
  and never touched.
- `fair-measure sync-docs --check` exits non-zero when the docs disagree with
  the JSON — wired into `just gates` and CI. Because the source is committed,
  CI can verify the docs without the data lake; JSON-vs-data consistency is
  guaranteed by export-web-stats being the file's only writer.

Workflow after a retrain: screen-assessments → export-web-stats → sync-docs
(`just export-stats` chains the last two) → commit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATS_PATH = Path("web/src/data/siteStats.json")

_MARKER = re.compile(
    r"(?P<begin><!-- generated:(?P<name>[a-z0-9-]+):begin -->\n)"
    r"(?P<body>.*?)"
    r"(?P<end><!-- generated:(?P=name):end -->)",
    re.DOTALL,
)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _card_row(label: str, card: dict[str, Any]) -> str:
    return _row(
        [
            label,
            f"{card['median_ratio']:.3f}",
            f"{card['cod']:.1f}",
            f"{card['prd']:.3f}",
            f"{card['prb']:+.3f}",
            f"{card['mape_pct']:.1f}%",
        ]
    )


def readme_screen_counts(stats: dict[str, Any]) -> str:
    s = stats["screen"]
    return (
        f"As of the latest run (Tax Year 2027 assessments), the screen covers\n"
        f"**{s['properties']:,}** residential properties and condos: **{s['over']:,}** flagged\n"
        f"as likely over-assessed, **{s['under']:,}** as likely under-assessed, and\n"
        f"**{s['watch']:,}** unflagged but at or beyond the edge of the published\n"
        f'range ("worth a look").\n'
        f"A residential flag requires two independent uncertainty methods — the\n"
        f"Bayesian posterior interval and a spatially weighted\n"
        f"conformalized-quantile-regression band — to both place the city's value\n"
        f"outside on the same side. {s['insufficient']} records with no recorded livable\n"
        f"area are reported as insufficient rather than valued.\n"
    )


def readme_results_tables(stats: dict[str, Any]) -> str:
    meta, iaao, full = stats["meta"], stats["iaao_card"], stats["full_card"]
    header = _row(["", "Median ratio", "COD", "PRD", "PRB", "MAPE"])
    divider = _row(["---"] * 6)
    return (
        f"Out-of-time test set (n = {meta['n_test']:,}), run `{meta['model_run_id']}`. The same\n"
        f"homes, the same treatment; OPA's assessed values are the incumbent benchmark.\n\n"
        f"On the IAAO ratio-study basis (financed, arm's-length sales — the standard\n"
        f"assessment offices are evaluated on):\n\n"
        f"{header}\n{divider}\n"
        f"{_card_row('This model', iaao['model'])}\n"
        f"{_card_row('OPA', iaao['opa'])}\n\n"
        f"On the full untrimmed sample, including cash and distressed sales:\n\n"
        f"{header}\n{divider}\n"
        f"{_card_row('This model', full['model'])}\n"
        f"{_card_row('OPA', full['opa'])}\n"
    )


def model_md_results_table(stats: dict[str, Any]) -> str:
    meta, table = stats["meta"], stats["results_table"]
    header = _row(["Model", "RMSE(log)", "MAPE", "Median ratio", "COD", "PRD", "PRB", "MKI"])
    divider = _row(["---"] * 8)

    def line(label: str, key: str, bold: bool = False) -> str:
        r = table[key]
        cells = [
            f"{r['rmse_log']:.3f}",
            f"{r['mape_pct']:.1f}%",
            f"{r['median_ratio']:.3f}",
            f"{r['cod']:.1f}",
            f"{r['prd']:.3f}",
            f"{r['prb']:+.3f}",
            f"{r['mki']:.3f}",
        ]
        if bold:
            cells = [f"**{c}**" if i in (0, 1, 3, 4, 5) else c for i, c in enumerate(cells)]
            label = f"**{label}**"
        return _row([label, *cells])

    return (
        f"Out-of-time test set, n≈19.5k, run `{meta['model_run_id']}`. Identical test\n"
        f"set and treatment; OPA's own values as the incumbent:\n\n"
        f"{header}\n{divider}\n"
        f"{line('LightGBM', 'lightgbm', bold=True)}\n"
        f"{line('Ridge', 'ridge')}\n"
        f"{line('OPA (incumbent)', 'opa_assessment', bold=True)}\n"
    )


def model_md_screen_counts(stats: dict[str, Any]) -> str:
    s, meta = stats["screen"], stats["meta"]
    return (
        f"As of run `{meta['model_run_id'].removesuffix('-baseline')}` (Tax Year 2027 roll): "
        f"{s['properties']:,} properties\n"
        f"screened — {s['over']:,} over-assessed candidates, {s['under']:,} under-assessed\n"
        f"candidates, {s['watch']:,} in the attention tier, {s['insufficient']} insufficient\n"
        f"records.\n"
    )


BLOCKS: dict[str, Any] = {
    "readme-screen-counts": readme_screen_counts,
    "readme-results-tables": readme_results_tables,
    "model-results-table": model_md_results_table,
    "model-screen-counts": model_md_screen_counts,
}

DOC_FILES = (Path("README.md"), Path("docs/model.md"))


@dataclass(frozen=True)
class SyncResult:
    changed: list[str]  # "file:block" identifiers that were (or would be) rewritten
    unknown: list[str]  # marker names with no registered builder


def sync_docs(repo_root: Path | None = None, *, check: bool = False) -> SyncResult:
    root = repo_root if repo_root is not None else Path.cwd()
    stats = json.loads((root / STATS_PATH).read_text())
    changed: list[str] = []
    unknown: list[str] = []
    for rel in DOC_FILES:
        path = root / rel
        text = path.read_text()

        def replace(match: re.Match[str], rel: Path = rel) -> str:
            name = match.group("name")
            builder = BLOCKS.get(name)
            if builder is None:
                unknown.append(f"{rel}:{name}")
                return match.group(0)
            body = builder(stats)
            if body != match.group("body"):
                changed.append(f"{rel}:{name}")
            return f"{match.group('begin')}{body}{match.group('end')}"

        new_text = _MARKER.sub(replace, text)
        if not check and new_text != text:
            path.write_text(new_text)
    return SyncResult(changed=changed, unknown=unknown)
