"""Sync generated number blocks in the docs from the committed stats JSON.

README.md, docs/model.md, and docs/vertical-equity-report-card.md quote screen
counts, results tables, and ratio-study report cards that change on every
retrain. Hand-editing them drifted repeatedly (the report card sat on a run
five generations stale); this module makes every run-dependent number
mechanical, so `sync-docs --check` in CI fails the moment a doc goes stale:

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
        f"A residential flag requires two independent uncertainty methods: the\n"
        f"Bayesian posterior interval and a spatially weighted\n"
        f"conformalized-quantile-regression band. Both must place the city's value\n"
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
        f"On the IAAO ratio-study basis (financed, arm's-length sales, the standard\n"
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
        f"screened: {s['over']:,} over-assessed candidates, {s['under']:,} under-assessed\n"
        f"candidates, {s['watch']:,} in the attention tier, {s['insufficient']} insufficient\n"
        f"records.\n"
    )


def _mark_ratio(v: float) -> str:
    return "✓" if 0.90 <= v <= 1.10 else "✗"


def _mark_cod(v: float) -> str:
    return "✓" if v <= 15 else "⚠︎" if v <= 20 else "✗"


def _mark_prd(v: float) -> str:
    return "✓" if 0.98 <= v <= 1.03 else "✗"


def _mark_prb(v: float) -> str:
    return "✓" if abs(v) <= 0.05 else "✗"


def _mark_vei(verdict: str) -> str:
    # the VEI verdict already encodes the standard's two-stage rule (±10% band,
    # then the CI-gap significance test), so the mark follows it directly
    return "✓" if verdict == "acceptable" else "✗"


def _veq_card(card: dict[str, Any], *, mape: bool) -> str:
    """A vertical-equity report-card table (OPA vs model) with IAAO pass marks."""
    opa, model = card["opa"], card["model"]
    rows = [
        _row(["Statistic", "Target", "OPA", "Our model"]),
        _row(["---"] * 4),
        _row(
            [
                "Median ratio",
                "0.90–1.10",
                f"{opa['median_ratio']:.3f} {_mark_ratio(opa['median_ratio'])}",
                f"{model['median_ratio']:.3f} {_mark_ratio(model['median_ratio'])}",
            ]
        ),
        _row(
            [
                "COD",
                "≤ 15",
                f"{opa['cod']:.1f} {_mark_cod(opa['cod'])}",
                f"{model['cod']:.1f} {_mark_cod(model['cod'])}",
            ]
        ),
        _row(
            [
                "PRD",
                "0.98–1.03",
                f"{opa['prd']:.3f} {_mark_prd(opa['prd'])}",
                f"{model['prd']:.3f} {_mark_prd(model['prd'])}",
            ]
        ),
        _row(
            [
                "PRB",
                "±0.05",
                f"{opa['prb']:+.3f} {_mark_prb(opa['prb'])}",
                f"{model['prb']:+.3f} {_mark_prb(model['prb'])}",
            ]
        ),
    ]
    if "vei" in opa:
        rows.append(
            _row(
                [
                    "VEI (2025 draft)",
                    "−10% to +10%",
                    f"{opa['vei']:+.1f}% {_mark_vei(str(opa['vei_verdict']))}",
                    f"{model['vei']:+.1f}% {_mark_vei(str(model['vei_verdict']))}",
                ]
            )
        )
    if mape:
        rows.append(_row(["MAPE", "n/a", f"{opa['mape_pct']:.1f}%", f"{model['mape_pct']:.1f}%"]))
    return "\n".join(rows) + "\n"


def veq_card_iaao(stats: dict[str, Any]) -> str:
    return _veq_card(stats["iaao_card"], mape=False)


def veq_card_full(stats: dict[str, Any]) -> str:
    return _veq_card(stats["full_card"], mape=True)


def veq_meta(stats: dict[str, Any]) -> str:
    m = stats["meta"]
    return (
        f"Numbers are the out-of-time test slice of baseline run\n"
        f"`{m['model_run_id']}` (n ≈ {m['n_test'] / 1000:.1f}k residential arms-length sales).\n"
        f"Reproduce with `fair-measure train-baseline` then `fair-measure ratio-study`. This\n"
        f'report card is deliberately not a "we made it fair" claim, see the honest '
        f"reading below.\n"
    )


def veq_robustness(stats: dict[str, Any]) -> str:
    """The Doucet-robustness table: individual-price vs neighborhood-level
    binning for OPA and the model, plus the Moran's-I map test."""
    rb = stats["equity_robustness"]

    def cell(c: dict[str, Any]) -> list[str]:
        return [
            f"{c['opa']['q1']:.2f}",
            f"{c['opa']['q5']:.2f}",
            f"{c['model']['q1']:.2f}",
            f"{c['model']['q5']:.2f}",
        ]

    rows = [
        ["all sales", "individual price", *cell(rb["all_sales"]["individual"])],
        ["all sales", "**neighborhood level**", *cell(rb["all_sales"]["neighborhood"])],
        ["all sales", "tract level (sensitivity)", *cell(rb["tract_sensitivity"])],
        ["financed", "individual price", *cell(rb["financed"]["individual"])],
        ["financed", "neighborhood level", *cell(rb["financed"]["neighborhood"])],
    ]
    m = rb["meta"]
    lines = [
        _row(["Basis", "Binned by", "City q1", "City q5", "Ours q1", "Ours q5"]),
        _row(["---"] * 6),
        *[_row(r) for r in rows],
        "",
        f"Map test (kNN Moran's I of log ratios, financed sales): city {m['morans_i_opa']:.3f}, "
        f"ours {m['morans_i_model']:.3f}. Zero means errors sprinkle randomly; higher means they",
        "cluster geographically, the signature of genuine neighborhood-level bias.",
        "",
        f"Neighborhoods are the {m['n_areas']} learned market areas with at least "
        f"{m['min_area_sales']} arms-length sales",
        f"(median {m['median_area_sales']} sales behind each area's price level); "
        f"{m['test_rows_without_area']:,} of {m['test_rows']:,} test sales carry",
        "no area assignment and are excluded from the neighborhood-binned rows.",
    ]
    return "\n".join(lines) + "\n"


def condo_bullet(stats: dict[str, Any]) -> str:
    """The condo accuracy line, shared by README limitations and model.md §6."""
    c, o = stats["condo_card"]["model"], stats["condo_card"]["opa"]
    return (
        f"- Condo accuracy: the model beats OPA on error (rmse {c['rmse_log']:.3f} vs "
        f"{o['rmse_log']:.3f}) and on\n"
        f"  uniformity (COD {c['cod']:.1f} vs {o['cod']:.1f}). Condos were long OPA's strongest "
        f"segment; the\n"
        f"  market-area price index closed the last gap.\n"
    )


BLOCKS: dict[str, Any] = {
    "readme-screen-counts": readme_screen_counts,
    "readme-results-tables": readme_results_tables,
    "model-results-table": model_md_results_table,
    "model-screen-counts": model_md_screen_counts,
    "veq-meta": veq_meta,
    "veq-card-iaao": veq_card_iaao,
    "veq-card-full": veq_card_full,
    "veq-robustness": veq_robustness,
    "condo-card": condo_bullet,
}

DOC_FILES = (
    Path("README.md"),
    Path("docs/model.md"),
    Path("docs/vertical-equity-report-card.md"),
)


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
