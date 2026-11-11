"""The API image must run the versions the project is locked and tested on.

The image installs the `serve` dependency group straight from `uv.lock`. A
hand-written requirements list (the previous setup) let every build resolve
whatever was newest on PyPI, which is how production came to run a different
polars major version from the one under test. These tests fail if the image
stops installing from the lock, or if the group drifts from `dependencies`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _name(requirement: str) -> str:
    """`uvicorn[standard]>=0.50` -> `uvicorn`."""
    return re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower()


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_serve_group_only_names_declared_dependencies() -> None:
    """The group lists names only; `dependencies` is where their versions are
    constrained, so a serve package missing from it would be unconstrained."""
    project = _pyproject()
    declared = {_name(req) for req in project["project"]["dependencies"]}
    serve = {_name(req) for req in project["dependency-groups"]["serve"]}
    assert serve, "the serve group is empty"
    assert serve <= declared, f"serve packages not in dependencies: {sorted(serve - declared)}"
    assert not any(re.search(r"[<>=~]", req) for req in project["dependency-groups"]["serve"]), (
        "list names only in the serve group; pin versions through dependencies and uv.lock"
    )


def test_lock_pins_every_serve_package() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    exported = subprocess.run(
        [uv, "export", "--frozen", "--only-group", "serve", "--no-emit-project", "--no-hashes"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pinned = {
        _name(line) for line in exported.splitlines() if "==" in line and not line.startswith("#")
    }
    serve = {_name(req) for req in _pyproject()["dependency-groups"]["serve"]}
    assert serve <= pinned, f"uv.lock does not pin: {sorted(serve - pinned)} (run `uv lock`)"


def test_dockerfile_installs_the_serve_group_from_the_lock() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert re.search(r"ghcr\.io/astral-sh/uv:\d+\.\d+", dockerfile), "pin the uv image tag"
    assert re.search(r"uv sync --frozen\b.*--only-group serve\b", dockerfile)
    assert "requirements" not in dockerfile, "install from uv.lock, not a requirements file"
    assert "!uv.lock" in (ROOT / ".dockerignore").read_text(), "uv.lock must reach the build"
