import polars as pl


def test_leaderboards_rank_by_confidence_and_uniformity(tmp_path):
    from philly_fair_measure.ingest.derived import write_derived_table
    from philly_fair_measure.ingest.manifests import InputRef
    from philly_fair_measure.report import leaderboards

    def row(
        pid, addr, opa, model, ratio, z, pi_lo, pi_hi, flag, twin_n=6, twin_med=1.0, shown=None
    ):
        shown = ratio if shown is None else shown  # OPA / the displayed estimate
        return {
            "parcel_id": pid,
            "address": addr,
            "opa_market_value": opa,
            "model_median": model,
            "opa_vs_model_ratio": ratio,
            "display_median": opa / shown,
            "display_ratio": shown,
            "screen_z": z,
            "model_pi_low_90": pi_lo,
            "model_pi_high_90": pi_hi,
            "assessment_flag": flag,
            "twin_n": twin_n,
            "opa_vs_twin_median": twin_med,
        }

    rows = [
        row(
            f"w{i}",
            f"{i} MAIN ST",
            200_000.0,
            200_000.0,
            1.0,
            0.0,
            180_000.0,
            220_000.0,
            "within_range",
        )
        for i in range(15)
    ]
    rows += [
        # over-assessed, tight intervals: ranked by screen_z, not ratio
        row(
            "over_confident",
            "1 HIGH ST",
            300_000.0,
            100_000.0,
            3.0,
            5.0,
            80_000.0,
            130_000.0,
            "over_assessed_candidate",
        ),
        row(
            "over_modest",
            "2 HIGH ST",
            180_000.0,
            120_000.0,
            1.5,
            2.0,
            100_000.0,
            150_000.0,
            "over_assessed_candidate",
        ),
        # biggest ratio but a 20x interval -> the model can't value it (blind spot)
        row(
            "over_blindspot",
            "9 HUGE ST",
            700_000.0,
            50_000.0,
            14.0,
            2.5,
            20_000.0,
            400_000.0,
            "over_assessed_candidate",
        ),
        # modest by the Bayesian median, the biggest gap against the shown estimate
        row(
            "over_shown",
            "3 HIGH ST",
            240_000.0,
            200_000.0,
            1.2,
            1.5,
            150_000.0,
            260_000.0,
            "over_assessed_candidate",
            shown=20.0,
        ),
        row(
            "under_x",
            "1 LOW ST",
            100_000.0,
            300_000.0,
            0.33,
            -4.0,
            250_000.0,
            380_000.0,
            "under_assessed_candidate",
        ),
        row(
            "odd_twin",
            "9 SAME ST",
            350_000.0,
            200_000.0,
            1.75,
            1.0,
            180_000.0,
            240_000.0,
            "within_range",
            twin_n=8,
            twin_med=1.5,
        ),
    ]
    write_derived_table(
        pl.DataFrame(rows),
        tmp_path,
        "marts",
        "assessment_screen",
        [InputRef(dataset="t", fetched_at="t")],
    )
    boards = leaderboards(tmp_path, n=5)  # default: interval-width filter + screen_z rank

    over = boards["over_assessed"]["parcel_id"].to_list()
    assert over[0] == "over_confident"  # highest screen_z, not highest ratio
    assert "over_blindspot" not in over  # 20x interval -> filtered as a blind spot
    assert boards["under_assessed"]["parcel_id"][0] == "under_x"  # most negative screen_z
    assert boards["non_uniform_block"]["parcel_id"][0] == "odd_twin"  # biggest twin gap

    assert boards["over_assessed"]["display_median"][0] == 300_000.0 / 3.0  # the shown estimate

    extremes = leaderboards(tmp_path, n=5, plausible=False)
    # raw biggest gaps against the shown estimate, blind spots included
    assert extremes["over_assessed"]["parcel_id"].to_list()[:2] == ["over_shown", "over_blindspot"]
