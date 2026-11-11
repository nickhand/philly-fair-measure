"""The canonical rebuild is `just snapshot-sources`, then `just retrain-all`.

Every step of `retrain-all` must find each input it requires: a raw snapshot
that `snapshot-sources` captures, or a table that an earlier step writes.
"""

import ast
import re
import shlex
from pathlib import Path

from philly_fair_measure import cli, config
from philly_fair_measure.staging.runner import BUILDERS, OPTIONAL_BUILDERS

JUSTFILE = Path(__file__).resolve().parents[1] / "Justfile"

# The lake tables a step writes that another step requires.
WRITES = {
    "stage": {f"staged/{table}.parquet" for table in BUILDERS},
    "validate-sales": {"marts/sale_validity.parquet"},
    "build-market-areas": {"marts/market_areas.parquet"},
    "build-price-index": {"marts/price_index.parquet"},
    "build-features": {"marts/sale_features.parquet"},
    "build-condo-features": {"marts/condo_sale_features.parquet"},
    "screen-assessments": {"marts/assessment_screen.parquet"},
}
# These write siteStats.json and the docs in the repository, so the test never runs them.
REPO_WRITERS = {"export-web-stats", "sync-docs"}


def _recipe(name: str) -> list[list[str]]:
    """The `fair-measure` arguments of each line of a Justfile recipe, in order."""
    lines = JUSTFILE.read_text().splitlines()
    if f"{name}:" not in lines:
        return []
    steps = []
    for line in lines[lines.index(f"{name}:") + 1 :]:
        if not line.startswith("\t"):
            break
        words = shlex.split(line)
        if words[:3] == ["uv", "run", "fair-measure"]:
            steps.append(words[3:])
    return steps


def _captures(step: list[str]) -> set[str]:
    if step[0] == "snapshot-all":
        return set(config.CORE_CARTO_TABLES)
    if step[0] == "snapshot":
        return {step[step.index("--dataset") + 1]}
    return set()


def _requires(step: list[str], lake: Path) -> set[str]:
    """The inputs a step refuses to start without.

    On an empty lake each run names one missing table. The loop creates that
    table as an empty file and runs the step again, until the step fails on
    something other than a missing table.
    """
    if step[0] == "stage":
        return {
            dataset
            for table, (_, datasets) in BUILDERS.items()
            if table not in OPTIONAL_BUILDERS
            for dataset in datasets
        }
    required: set[str] = set()
    while True:
        try:
            cli.main([*step, "--data-dir", str(lake)])
        except FileNotFoundError as exc:
            message = str(exc)
        except Exception:
            return required  # it read an empty placeholder, so no table is missing
        else:
            return required
        table = re.search(r"(\S+\.parquet) missing", message)
        if table is None:
            snapshots = re.search(r"raw snapshots (\[[^\]]*\])", message)
            return required | (set(ast.literal_eval(snapshots.group(1))) if snapshots else set())
        path = Path(table.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        required.add(path.relative_to(lake).as_posix())


def test_retrain_all_finds_every_input_it_requires(tmp_path):
    steps = _recipe("retrain-all")
    assert steps, "the Justfile has no retrain-all recipe"
    available = set().union(*(_captures(step) for step in _recipe("snapshot-sources")))

    unmet = []
    for index, step in enumerate(steps):
        if step[0] in REPO_WRITERS:
            continue
        missing = _requires(step, tmp_path / str(index)) - available
        unmet += [f"{step[0]} needs {need}" for need in sorted(missing)]
        available |= WRITES.get(step[0], set())

    assert not unmet, "\n".join(unmet)
