from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()
PACKAGE = json.loads((ROOT / "web/package.json").read_text())


class ReleaseContractTests(unittest.TestCase):
    def test_production_can_only_use_the_guarded_workflow(self) -> None:
        scripts = PACKAGE["scripts"]
        self.assertNotIn("deploy:cloudflare:production", scripts)
        self.assertNotIn("wrangler deploy --env production", "\n".join(scripts.values()))
        self.assertIn("environment:\n      name: frontend-production", WORKFLOW)

    def test_reruns_reuse_one_candidate_and_original_rollback_version(self) -> None:
        self.assertIn('tag="github-${GITHUB_RUN_ID}"', WORKFLOW)
        self.assertNotIn('tag="github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"', WORKFLOW)
        self.assertIn("previous=${PREVIOUS_VERSION}", WORKFLOW)
        self.assertIn("Reconcile an interrupted earlier attempt", WORKFLOW)
        self.assertIn("Find or upload the exact validated Worker version", WORKFLOW)

    def test_activation_and_rollback_reconcile_terminal_state(self) -> None:
        self.assertGreaterEqual(
            WORKFLOW.count("for _ in {1..10}; do"),
            4,
            "upload, retry reconciliation, activation, and rollback must poll exact state",
        )
        self.assertIn("Attest the terminal active Worker version", WORKFLOW)
        self.assertIn("Reconcile or roll back an unverified activation", WORKFLOW)
        self.assertIn("steps.deploy.outcome != 'success'", WORKFLOW)

    def test_release_checks_exact_files_and_a_hydrated_browser(self) -> None:
        self.assertIn("--artifact-directory dist", WORKFLOW)
        self.assertIn("--attempts 30", WORKFLOW)
        self.assertIn("--retry-delay-ms 10000", WORKFLOW)
        self.assertIn("check-cloudflare-browser.mjs", WORKFLOW)
        self.assertIn("mcr.microsoft.com/playwright:v1.62.0-noble@sha256:", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
