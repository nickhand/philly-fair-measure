#!/usr/bin/env python3
"""Route Fair Measure CI and production releases from changed paths."""

from __future__ import annotations

import sys
from collections.abc import Iterable

WEB_SUPPORT_FILES = {
    ".github/ci/scope.py",
    ".github/ci/test_release_contracts.py",
    ".github/ci/test_scope.py",
    ".github/workflows/ci.yml",
    "Justfile",
    "docs/frontend.md",
    "netlify.toml",
}
NON_RELEASE_WEB_FILES = {"web/README.md"}
NON_RELEASE_WEB_PREFIXES = ("web/tests/", "web/src/__tests__/")


def classify(paths: Iterable[str]) -> dict[str, bool]:
    """Select Python/web checks and runtime releases, failing closed on unknown paths."""

    normalized = {path.strip().removeprefix("./") for path in paths if path.strip()}
    if not normalized:
        return {"python": True, "web": True, "release": True}

    web_related = {
        path for path in normalized if path.startswith("web/") or path in WEB_SUPPORT_FILES
    }
    python_related = normalized - web_related
    release_related = {
        path
        for path in web_related
        if (
            path in {".github/ci/scope.py", ".github/workflows/ci.yml"}
            or (
                path.startswith("web/")
                and path not in NON_RELEASE_WEB_FILES
                and not path.startswith(NON_RELEASE_WEB_PREFIXES)
            )
        )
    }
    return {
        "python": bool(python_related),
        "web": bool(web_related),
        "release": bool(release_related),
    }


def main() -> int:
    selection = classify(sys.stdin)
    for key in ("python", "web", "release"):
        print(f"{key}={str(selection[key]).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
