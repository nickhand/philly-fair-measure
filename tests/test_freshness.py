"""freshness: the heartbeat checks the tables the weekly job captures."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from philly_fair_measure import cli, config
from philly_fair_measure.ingest.manifests import MANIFEST_FILENAME
from philly_fair_measure.ingest.snapshots import DATA_FILENAME, FETCHED_AT_FORMAT


def _snapshot(data_dir: Path, dataset: str, age: timedelta) -> None:
    stamp = (datetime.now(UTC) - age).strftime(FETCHED_AT_FORMAT)
    directory = data_dir / "raw" / "source=carto" / f"dataset={dataset}" / f"fetched_at={stamp}"
    directory.mkdir(parents=True)
    (directory / DATA_FILENAME).touch()
    (directory / MANIFEST_FILENAME).touch()


def _checked(out: str) -> set[str]:
    return {line.split()[0] for line in out.splitlines()}


def test_freshness_passes_when_every_scheduled_table_is_fresh(tmp_path, capsys):
    for table in config.SCHEDULED_CARTO_TABLES:
        _snapshot(tmp_path, table, timedelta(days=1))

    assert cli.main(["freshness", "--data-dir", str(tmp_path)]) == 0
    assert _checked(capsys.readouterr().out) == set(config.SCHEDULED_CARTO_TABLES)


@pytest.mark.parametrize("age", [timedelta(days=9), None], ids=["stale", "missing"])
def test_freshness_fails_when_a_scheduled_table_is_stale_or_missing(tmp_path, capsys, age):
    late, *others = config.SCHEDULED_CARTO_TABLES
    for table in others:
        _snapshot(tmp_path, table, timedelta(days=1))
    if age is not None:
        _snapshot(tmp_path, late, age)

    assert cli.main(["freshness", "--data-dir", str(tmp_path)]) == 1
    flagged = [line for line in capsys.readouterr().out.splitlines() if "ok" not in line.split()]
    assert [line.split()[0] for line in flagged] == [late]
