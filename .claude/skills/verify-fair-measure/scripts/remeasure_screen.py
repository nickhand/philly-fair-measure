#!/usr/bin/env python3
"""Recount the published screen numbers from the mart and compare every place they appear.

Run from the checkout root. Reads $PHILLY_DATA_DIR (default data/)/marts/assessment_screen.parquet
read-only, recounts the flags with polars, and compares the counts with
web/src/data/siteStats.json, the screen manifest's model runs, and optionally a running API
and the prerendered home page. `fm-verify remeasure <slug> [--api URL] [--html FILE]` runs it
with --out in the evidence folder.

Exits 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
import polars as pl


class VisibleText(HTMLParser):
    """Text a visitor reads: no comments, attributes, or script and style contents."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden += 1
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def visible_text(html: str) -> str:
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def recount(screen: Path) -> dict[str, Any]:
    df = pl.read_parquet(screen, columns=["model_family", "assessment_flag", "attention"])
    by = {
        f"{r['model_family']}/{r['assessment_flag']}": r["len"]
        for r in df.group_by("model_family", "assessment_flag").len().to_dicts()
    }

    def total(flag: str) -> int:
        return sum(int(n) for key, n in by.items() if key.endswith(f"/{flag}"))

    return {
        "properties": df.height,
        "over": total("over_assessed_candidate"),
        "under": total("under_assessed_candidate"),
        "watch": df.filter(pl.col("attention").is_not_null()).height,
        "insufficient": total("insufficient_record"),
        "by_family_flag": dict(sorted(by.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ.get("PHILLY_DATA_DIR", "data"))
    )
    parser.add_argument("--stats", type=Path, default=Path("web/src/data/siteStats.json"))
    parser.add_argument("--api", help="base URL of a running API to compare /api/stats")
    parser.add_argument(
        "--html", type=Path, help="prerendered home page whose visible text must show each count"
    )
    parser.add_argument("--out", type=Path, help="write the comparison as JSON here")
    args = parser.parse_args()

    screen = args.data_dir / "marts" / "assessment_screen.parquet"
    manifest = json.loads(screen.with_suffix(".manifest.json").read_text())
    stats = json.loads(args.stats.read_text())
    mart = recount(screen)
    published = stats["screen"]
    rows: list[tuple[str, object, object]] = [
        ("manifest.row_count", manifest["row_count"], mart["properties"]),
    ]
    rows += [(f"siteStats.screen.{k}", published[k], mart[k]) for k in mart]

    runs = [i["dataset"].removeprefix("models/") for i in manifest["inputs"]]
    for key in ("model_run_id", "interval_run_id"):
        rows.append((f"siteStats.meta.{key} in screen inputs", stats["meta"][key] in runs, True))

    if args.api:
        live = httpx.get(f"{args.api.rstrip('/')}/api/stats", timeout=30).json()
        rows += [
            (f"api /api/stats.{k}", live[k], mart[k])
            for k in ("properties", "over", "under", "watch")
        ]

    if args.html:
        text = visible_text(args.html.read_text())
        for label, n in (
            ("homes we valued citywide", mart["properties"]),
            ("flagged outside our range", mart["over"] + mart["under"]),
            ("more worth a closer look", mart["watch"]),
        ):
            shown = f"{n:,} {label}"
            rows.append((f"{args.html.name} shows '{shown}'", shown in text, True))

    mismatches = [r for r in rows if r[1] != r[2]]
    print(f"screen mart {screen.resolve()} built {manifest['built_at'][:19]}")
    print(f"model runs: {', '.join(runs[:3])}")
    for name, got, want in rows:
        mark = "ok  " if got == want else "DIFF"
        print(f"  {mark} {name}: {got} (mart: {want})")
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "screen": str(screen.resolve()),
                    "built_at": manifest["built_at"],
                    "runs": runs,
                    "mart": mart,
                    "checks": [{"check": n, "got": g, "want": w, "ok": g == w} for n, g, w in rows],
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        print(f"wrote {args.out}")
    verdict = "MISMATCH" if mismatches else "OK"
    print(f"remeasure: {verdict} ({len(rows)} checks, {len(mismatches)} differ)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
