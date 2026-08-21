from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("scope.py")
SPEC = importlib.util.spec_from_file_location("fair_measure_scope", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


class ScopeTests(unittest.TestCase):
    def test_runtime_web_change_selects_release_only(self) -> None:
        self.assertEqual(
            SCOPE.classify(["web/src/App.vue"]),
            {"python": False, "web": True, "release": True},
        )

    def test_web_test_or_retirement_docs_do_not_publish(self) -> None:
        self.assertEqual(
            SCOPE.classify(["web/tests/worker-routes.test.mjs", "docs/frontend.md"]),
            {"python": False, "web": True, "release": False},
        )

    def test_snapshot_or_python_change_does_not_select_web(self) -> None:
        self.assertEqual(
            SCOPE.classify(["docs/snapshots/2026-08-21.md", "src/philly_fair_measure/api.py"]),
            {"python": True, "web": False, "release": False},
        )

    def test_mixed_change_runs_both_and_releases(self) -> None:
        self.assertEqual(
            SCOPE.classify(["pyproject.toml", "web/wrangler.jsonc"]),
            {"python": True, "web": True, "release": True},
        )

    def test_release_pipeline_change_exercises_a_release(self) -> None:
        self.assertEqual(
            SCOPE.classify(
                [
                    ".github/workflows/ci.yml",
                    ".github/ci/test_release_contracts.py",
                    ".github/ci/test_scope.py",
                ]
            ),
            {"python": False, "web": True, "release": True},
        )

    def test_empty_input_fails_closed(self) -> None:
        self.assertEqual(
            SCOPE.classify([]),
            {"python": True, "web": True, "release": True},
        )


if __name__ == "__main__":
    unittest.main()
