"""Run snapshot.yml's own step scripts against stub `aws` and `gh` commands."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/snapshot.yml").read_text()
CI_WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()
PULL_STEP = "Pull previous snapshots from S3 (latest per dataset)"
ALERT_STEP = "Open or update the snapshot failure issue"
ALERT_TITLE = "Snapshot workflow failed"
OPA = "raw/source=carto/dataset=opa_properties_public/"
RUN_URL = "https://github.com/owner/repo/actions/runs/42"

# Mirrors the AWS CLI v2: `s3 ls` exits 1 when a prefix holds nothing, while
# `s3api list-objects-v2` prints JSON without CommonPrefixes and exits 0.
STUB = textwrap.dedent(
    """
    import json, os, sys
    tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write(json.dumps([tool, *args]) + "\\n")
    fixture = json.loads(open(os.environ["STUB_FIXTURE"]).read())

    def prefixes(bucket, prefix):
        if bucket == "denied":
            sys.stderr.write("An error occurred (AccessDenied) when calling ListObjectsV2\\n")
            sys.exit(254)
        rests = [k[len(prefix):] for k in fixture.get(bucket, []) if k.startswith(prefix)]
        return sorted({prefix + r.split("/", 1)[0] + "/" for r in rests if "/" in r})

    if tool == "gh":
        if args[:2] == ["issue", "list"]:
            print(json.dumps(fixture["issues"]))
    elif args[:2] == ["s3", "ls"]:
        bucket, _, prefix = args[2].removeprefix("s3://").partition("/")
        found = prefixes(bucket, prefix)
        if not found:
            sys.exit(1)
        for p in found:
            print(f"{'PRE':>30} {p[len(prefix):]}")
    elif args[:2] == ["s3api", "list-objects-v2"]:
        opts = dict(zip(args[2::2], args[3::2]))
        assert set(opts) <= {"--bucket", "--prefix", "--delimiter", "--output"}, opts
        assert opts.get("--delimiter") == "/" and opts.get("--output", "json") == "json", opts
        found = prefixes(opts["--bucket"], opts["--prefix"])
        out = {"CommonPrefixes": [{"Prefix": p} for p in found]} if found else {}
        print(json.dumps({**out, "RequestCharged": None, "Prefix": opts["--prefix"]}))
    elif args[:2] != ["s3", "sync"]:
        sys.exit(f"stub does not implement: {args}")
    """
)


def step(name: str) -> str:
    lines = WORKFLOW.splitlines()
    for start, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            break
    else:
        raise AssertionError(f"snapshot.yml has no step named {name!r}")
    indent = len(line) - len(line.lstrip())
    end = start + 1
    while end < len(lines) and (
        not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent
    ):
        end += 1
    return "\n".join(lines[start:end])


def run_step(
    name: str, fixture: dict[str, object], env: dict[str, str], bucket: str = "snapshots"
) -> tuple[int, str, list[list[str]]]:
    script = textwrap.dedent(step(name).split("run: |\n", 1)[1])
    script = script.replace("${{ vars.SNAPSHOT_BUCKET }}", bucket)
    assert "${{" not in script, script
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("aws", "gh"):
            stub = bin_dir / tool
            stub.write_text(f"#!{sys.executable}\n{STUB}")
            stub.chmod(0o755)
        (tmp_path / "fixture.json").write_text(json.dumps(fixture))
        log = tmp_path / "calls.jsonl"
        log.touch()
        result = subprocess.run(
            ["bash", "-e", "-c", script],
            cwd=tmp_path,
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_FIXTURE": str(tmp_path / "fixture.json"),
                "STUB_LOG": str(log),
                **env,
            },
            capture_output=True,
            text=True,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result.returncode, result.stdout + result.stderr, calls


class PullPreviousSnapshotsTests(unittest.TestCase):
    def test_a_new_table_is_a_first_run_beside_one_with_history(self) -> None:
        bucket = [
            f"{OPA}fetched_at=20261102T042512Z/data.parquet",
            f"{OPA}fetched_at=20261109T042736Z/data.parquet",
            f"{OPA}fetched_at=20261116T042300Z.incomplete/data.parquet",
        ]
        code, output, calls = run_step(
            PULL_STEP,
            {"snapshots": bucket},
            {"TABLES": "opa_properties_public assessments"},
        )
        self.assertEqual(code, 0, output)
        latest = f"{OPA}fetched_at=20261109T042736Z/"
        self.assertEqual(
            [call[-2:] for call in calls if call[1:3] == ["s3", "sync"]],
            [[f"s3://snapshots/{latest}", f"data/{latest}"]],
        )
        self.assertIn("no previous snapshot for assessments", output)

    def test_a_denied_listing_still_fails(self) -> None:
        code, _, calls = run_step(
            PULL_STEP, {}, {"TABLES": "opa_properties_public"}, bucket="denied"
        )
        self.assertNotEqual(code, 0)
        self.assertFalse([call for call in calls if call[1:3] == ["s3", "sync"]])


class FailureAlertTests(unittest.TestCase):
    env = {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "42",
    }

    def test_first_failure_opens_an_issue_with_the_run_url(self) -> None:
        code, output, calls = run_step(ALERT_STEP, {"issues": []}, self.env)
        self.assertEqual(code, 0, output)
        writes = [call for call in calls if call[1:3] != ["issue", "list"]]
        self.assertEqual([call[1:3] for call in writes], [["issue", "create"]])
        self.assertIn(ALERT_TITLE, writes[0])
        self.assertTrue(any(RUN_URL in arg for arg in writes[0]), writes[0])

    def test_later_failure_comments_on_the_open_issue(self) -> None:
        issues = [{"number": 3, "title": "Unrelated"}, {"number": 12, "title": ALERT_TITLE}]
        code, output, calls = run_step(ALERT_STEP, {"issues": issues}, self.env)
        self.assertEqual(code, 0, output)
        writes = [call for call in calls if call[1:3] != ["issue", "list"]]
        self.assertEqual([call[1:4] for call in writes], [["issue", "comment", "12"]])
        self.assertTrue(any(RUN_URL in arg for arg in writes[0]), writes[0])

    def test_alert_runs_on_failure_with_issue_write_permission(self) -> None:
        self.assertIn("if: failure()", step(ALERT_STEP))
        self.assertRegex(WORKFLOW, r"(?m)^  issues: write\b")


class PinTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit(self) -> None:
        actions = re.findall(r"uses:\s*(\S+)", WORKFLOW)
        self.assertTrue(actions)
        for action in actions:
            self.assertRegex(action, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

    def test_runner_is_the_image_ci_tests_on(self) -> None:
        self.assertEqual(
            set(re.findall(r"runs-on:\s*(\S+)", WORKFLOW)),
            set(re.findall(r"runs-on:\s*(\S+)", CI_WORKFLOW)),
        )


if __name__ == "__main__":
    unittest.main()
