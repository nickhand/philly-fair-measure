#!/usr/bin/env python3
"""Read-only health report: is this checkout and its running instances worth driving?

Run from the worktree root: uv run python .claude/skills/verify-fair-measure/scripts/doctor.py
Exits 1 when a hard check fails. Never starts, stops, or writes anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import polars as pl

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def warn(msg: str) -> None:
    print(f"  warn  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    failures.append(msg)


def sh(*cmd: str) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return done.stdout.strip()


@dataclass(frozen=True)
class Listener:
    pid: int
    pgid: int
    command: str
    cwd: Path
    env: str


def listener(port: int) -> Listener | None:
    pids = sh("lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN").split()
    if not pids:
        return None
    pid = int(pids[0])
    cwd = next(
        (
            line[1:]
            for line in sh("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines()
            if line.startswith("n")
        ),
        "?",
    )
    return Listener(
        pid=pid,
        pgid=int(sh("ps", "-o", "pgid=", "-p", str(pid)) or 0),
        command=sh("ps", "-o", "command=", "-p", str(pid)),
        cwd=Path(cwd),
        env=sh("ps", "eww", "-o", "command=", "-p", str(pid)),
    )


def owned_groups(slug: str | None) -> dict[int, str]:
    if not slug:
        return {}
    scratch = Path(os.environ.get("TMPDIR", "/tmp")) / "fm-verify" / slug
    return {int(p.read_text()): p.stem for p in scratch.glob("*.pid")}


def describe(name: str, port: int, owned: dict[int, str]) -> Listener | None:
    proc = listener(port)
    if proc is None:
        print(f"  --    {name}: nothing listening on {port}")
        return None
    who = (
        f"started by this run as '{owned[proc.pgid]}'"
        if proc.pgid in owned
        else "NOT started by this run"
    )
    print(f"  ..    {name} :{port} pid {proc.pid} ({who})")
    print(f"        cmd {proc.command}")
    print(f"        cwd {proc.cwd}")
    if proc.pgid not in owned:
        warn(f"{name} on :{port} belongs to someone else; read it, never stop it")
    return proc


def served_data_dir(proc: Listener) -> Path:
    flag = re.search(r"--data-dir\s+(\S+)", proc.command)
    env = re.search(r"\bPHILLY_DATA_DIR=(\S+)", proc.env)
    chosen = flag or env
    return (proc.cwd / (str(chosen.group(1)) if chosen else "data")).resolve()


def screen_facts(data_dir: Path) -> tuple[int, str, list[str]] | None:
    screen = data_dir / "marts" / "assessment_screen.parquet"
    manifest = screen.with_suffix(".manifest.json")
    if not screen.exists():
        return None
    rows = int(pl.scan_parquet(screen).select(pl.len()).collect().item())
    meta = json.loads(manifest.read_text()) if manifest.exists() else {}
    runs = [str(i["dataset"]) for i in meta.get("inputs", [])]
    return rows, str(meta.get("built_at", "?"))[:10], [r for r in runs if r.startswith("models/")]


def check_checkout(root: Path) -> None:
    print("checkout")
    branch = sh("git", "-C", str(root), "branch", "--show-current") or "(detached)"
    head = sh("git", "-C", str(root), "rev-parse", "--short", "HEAD")
    dirty = len(sh("git", "-C", str(root), "status", "--porcelain").splitlines())
    print(f"  ..    {root} on {branch} @ {head}, {dirty} dirty")
    for link, probe in (
        ("data", "marts/assessment_screen.parquet"),
        ("deploy", "data/marts/assessment_screen.parquet"),
        ("web/node_modules", ".bin/vite"),
    ):
        path = root / link
        if (path / probe).exists():
            ok(f"{link} -> {path.resolve()}")
        else:
            fail(f"{link}/{probe} missing; run fm-verify setup <slug>")
    lake = Path(os.environ.get("PHILLY_DATA_DIR", root / "data")).resolve()
    facts = screen_facts(lake)
    if facts:
        rows, built, runs = facts
        ok(f"lake {lake}: assessment_screen {rows:,} rows, built {built}, from {', '.join(runs)}")
    stats = json.loads((root / "web/src/data/siteStats.json").read_text())
    meta, screen = stats["meta"], stats["screen"]
    print(
        f"  ..    siteStats.json: run {meta['model_run_id']}, generated {meta['generated_at']}, "
        f"screen.properties {screen['properties']:,}"
    )


def check_api(port: int, owned: dict[int, str]) -> None:
    print("api")
    proc = describe("api", port, owned)
    if proc is None:
        return
    base = f"http://127.0.0.1:{port}"
    try:
        health = httpx.get(f"{base}/health", timeout=10).json()
        stats = httpx.get(f"{base}/api/stats", timeout=10).json()
    except (httpx.HTTPError, ValueError) as err:
        fail(f"api on :{port} does not answer /health and /api/stats: {err}")
        return
    if health.get("status") != "ok":
        fail(f"/health says {health}")
        return
    ok(f"/health rows {health['rows']:,}, screen_built {health['screen_built']}")
    ok(f"/api/stats over {stats['over']:,} under {stats['under']:,} watch {stats['watch']:,}")
    data_dir = served_data_dir(proc)
    facts = screen_facts(data_dir)
    if facts is None:
        fail(f"cannot find the screen the api serves under {data_dir}")
        return
    rows, built, runs = facts
    if rows == health["rows"] and built == health["screen_built"]:
        ok(f"serves {data_dir} (screen {rows:,} rows, built {built}, {', '.join(runs)})")
    else:
        fail(
            f"api reports {health['rows']:,} rows built {health['screen_built']}, "
            f"but {data_dir} has {rows:,} built {built}; restart it"
        )


def check_site(
    root: Path, api_port: int, preview_port: int, dev_port: int, owned: dict[int, str]
) -> None:
    print("site")
    dist = root / "web/dist"
    # a stale dist only matters when the preview serves it
    flag = fail if listener(preview_port) else warn
    if not (dist / "index.html").exists():
        warn("web/dist missing; fm-verify build-site <slug> builds it")
    else:
        bundle = "\n".join(p.read_text(errors="ignore") for p in (dist / "assets").glob("*.js"))
        if "phc_" in bundle:
            flag("web/dist has PostHog analytics compiled in; rebuild with fm-verify build-site")
        else:
            ok("web/dist built with analytics off")
        bases = sorted(set(re.findall(r"http://127\.0\.0\.1:\d+", bundle)))
        want = f"http://127.0.0.1:{api_port}"
        if want in bases:
            ok(f"web/dist calls the api at {want}")
        else:
            flag(
                f"web/dist calls {bases or 'same-origin /api'}, not {want}; npm run preview "
                "answers /api with the SPA shell, so rebuild with fm-verify build-site"
            )
    for name, port in (("preview", preview_port), ("dev", dev_port)):
        proc = describe(name, port, owned)
        if proc is None:
            continue
        base = f"http://127.0.0.1:{port}"
        try:
            home = httpx.get(f"{base}/", timeout=10)
            proxied = httpx.get(f"{base}/api/stats", timeout=10) if name == "dev" else None
        except httpx.HTTPError as err:
            fail(f"{name} on :{port} does not answer: {err}")
            continue
        rendered = 'data-server-rendered="true"' in home.text
        if home.status_code == 200 and (rendered or name == "dev"):
            ok(f"{name} / -> 200{' prerendered' if rendered else ''}")
        else:
            fail(f"{name} / -> {home.status_code}, prerendered={rendered}")
        if proxied is None:
            continue
        if proxied.headers.get("content-type", "").startswith("application/json"):
            ok("dev /api/stats -> JSON through the vite proxy to 127.0.0.1:8000")
        else:
            warn(f"dev /api/stats -> {proxied.status_code} non-JSON; the proxy reaches :8000 only")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--preview-port", type=int, default=4173)
    parser.add_argument("--dev-port", type=int, default=5173)
    args = parser.parse_args()
    root = Path(sh("git", "rev-parse", "--show-toplevel"))
    owned = owned_groups(args.slug)
    check_checkout(root)
    check_api(args.api_port, owned)
    check_site(root, args.api_port, args.preview_port, args.dev_port, owned)
    print(f"doctor: {'FAIL' if failures else 'OK'} ({len(failures)} hard failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
