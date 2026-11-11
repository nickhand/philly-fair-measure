"""The weekly snapshot job and `just snapshot-current` fetch the scheduled tables."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/snapshot.yml").read_text()
JUSTFILE = (ROOT / "Justfile").read_text()


def scheduled_tables() -> list[str]:
    # config.py imports only the standard library, so CI's bare python3 can load it.
    path = ROOT / "src/philly_fair_measure/config.py"
    spec = importlib.util.spec_from_file_location("config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.SCHEDULED_CARTO_TABLES)


def fetched_tables(script: str, env: dict[str, str]) -> list[str]:
    """The tables a `snapshot-all --tables ...` line names, with `$VAR`s expanded."""
    found = re.findall(r"fair-measure snapshot-all --tables (.+)", script)
    assert len(found) == 1, f"expected one snapshot-all --tables line, found {found}"
    tables = []
    for word in found[0].split():
        tables.extend(env[word[1:]].split() if word.startswith("$") else [word])
    return tables


class ScheduledTablesTests(unittest.TestCase):
    def test_the_workflow_fetches_the_scheduled_tables(self) -> None:
        env = {
            name: value.split(" #")[0]
            for name, value in re.findall(r"(?m)^  ([A-Z_]+): (.+)$", WORKFLOW)
        }
        self.assertCountEqual(fetched_tables(WORKFLOW, env), scheduled_tables())

    def test_snapshot_current_fetches_the_scheduled_tables(self) -> None:
        recipe = re.search(r"(?m)^snapshot-current:\n((?:\t.*\n)+)", JUSTFILE)
        assert recipe is not None, "Justfile has no snapshot-current recipe"
        self.assertCountEqual(fetched_tables(recipe.group(1), {}), scheduled_tables())


if __name__ == "__main__":
    unittest.main()
