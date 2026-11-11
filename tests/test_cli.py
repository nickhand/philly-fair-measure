import polars as pl
import pytest

from philly_fair_measure.cli import main
from philly_fair_measure.ingest.derived import write_derived_table
from philly_fair_measure.ingest.manifests import InputRef


def _screen(tmp_path):
    def row(pid, opa, model, display, flag):
        return {
            "parcel_id": pid,
            "address": f"{pid} MAIN ST",
            "opa_market_value": opa,
            "model_median": model,
            "model_pi_low_90": model * 0.7,
            "model_pi_high_90": model * 1.4,
            "opa_vs_model_ratio": opa / model,
            "display_median": display,
            "display_pi_low_90": display * 0.8,
            "display_pi_high_90": display * 1.25,
            "display_ratio": opa / display,
            "screen_z": 4.0 if flag == "over_assessed_candidate" else 0.0,
            "assessment_flag": flag,
            "interval_method": "bayesian_posterior",
            "twin_n": 6,
            "opa_vs_twin_median": 1.0,
        }

    rows = [row("100000001", 900_000.0, 300_000.0, 360_000.0, "over_assessed_candidate")]
    rows += [row(f"20000000{i}", 200_000.0, 210_000.0, 205_000.0, "within_range") for i in range(5)]
    write_derived_table(
        pl.DataFrame(rows),
        tmp_path,
        "marts",
        "assessment_screen",
        [InputRef(dataset="t", fetched_at="t")],
    )


def test_leaderboard_prints_the_displayed_estimate(tmp_path, capsys):
    _screen(tmp_path)
    assert main(["leaderboard", "--kind", "over", "--n", "5", "--data-dir", str(tmp_path)]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "100000001" in x)
    assert "360,000" in line and "2.5x" in line  # the estimate the report page shows
    assert "300,000" not in line  # not the Bayesian median


def test_comps_prints_the_displayed_estimate(tmp_path, capsys, monkeypatch):
    from philly_fair_measure.models import comps

    _screen(tmp_path)
    target = {"parcel_id": "100000001", "address": "100000001 MAIN ST"}
    monkeypatch.setattr(comps, "resolve_parcel", lambda query, data_dir: [target])
    monkeypatch.setattr(
        comps,
        "find_comps",
        lambda parcel_id, data_dir, **_: comps.CompsResult(
            target=target, comps=pl.DataFrame(schema={"address": pl.String})
        ),
    )
    assert main(["comps", "100000001", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "$360,000" in out  # the shown estimate
    assert "$288,000 - $450,000" in out  # with its own shown range
    assert "$300,000 " not in out


def test_stage_rejects_an_unknown_table_name(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["stage", "--tables", "permit", "--data-dir", str(tmp_path)])
    assert exit_info.value.code == 2  # an argparse usage error, not a traceback
    err = capsys.readouterr().err
    assert "permit" in err and "permits" in err  # names the valid tables
    assert not (tmp_path / "staged").exists()  # nothing was touched
