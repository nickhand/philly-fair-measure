import numpy as np


def test_appeal_points_filters_correctable_and_flags_implausible():
    from philly_assessments.models.explain import Driver, Explanation, appeal_points

    exp = Explanation(
        value=200_000.0,
        base_value=249_000.0,
        drivers=[
            Driver("char_livable_area", "living area", "Home characteristics",
                   420.0, -0.4, -80_000.0),
            Driver("mkt_knn_log_ppsf", "nearby recent sale prices", "Recent nearby sales",
                   None, 0.2, 40_000.0),
            Driver("char_beds", "bedrooms", "Home characteristics", 3.0, 0.05, 9_000.0),
        ],
    )
    pts = appeal_points(exp, {"char_livable_area": 420.0, "char_beds": 3.0})

    features = [p.feature for p in pts]
    assert "mkt_knn_log_ppsf" not in features  # market signal isn't a correctable fact
    assert set(features) == {"char_livable_area", "char_beds"}
    # implausible 420 sqft sorts first and is flagged; a normal bed count is not
    assert pts[0].feature == "char_livable_area" and pts[0].implausible
    assert not pts[1].implausible


def test_explain_is_faithful_ranked_and_readable(tmp_path):
    from philly_assessments.ingest.derived import write_derived_table
    from philly_assessments.ingest.manifests import InputRef
    from philly_assessments.models.baseline import train_baseline
    from philly_assessments.models.explain import explain, plain_language
    from philly_assessments.models.scoring import score_lightgbm
    from tests.test_baseline import _synthetic_mart

    frame = _synthetic_mart()
    write_derived_table(
        frame, tmp_path, "marts", "sale_features", [InputRef(dataset="test", fetched_at="t")]
    )
    result = train_baseline(
        tmp_path,
        test_fraction=0.15,
        lgb_params={"num_leaves": 15, "min_data_in_leaf": 5, "learning_rate": 0.1},
        num_boost_round=200,
        early_stopping_rounds=30,
    )

    sample = frame.head(6)
    exps = explain(result.run_dir, sample)
    assert len(exps) == sample.height

    # faithfulness: the explained value is exactly the value score_lightgbm serves
    scored = score_lightgbm(result.run_dir, sample)
    assert np.allclose([e.value for e in exps], scored, rtol=1e-6)

    for e in exps:
        assert e.value > 0 and e.base_value > 0
        assert e.drivers  # a model with signal attributes something
        # mortgage-history features stay in the model but not in the lay panels
        assert not any(d.feature.startswith("fin_") for d in e.drivers)
        # drivers are ranked by absolute contribution, largest first
        mags = [abs(d.contribution) for d in e.drivers]
        assert mags == sorted(mags, reverse=True)
        assert e.by_group()  # category-level view is non-empty
        # plain language: one line per requested driver, sign consistent with it
        lines = plain_language(e, 4)
        assert len(lines) == min(4, len(e.drivers))
        for d, line in zip(e.top(4), lines, strict=True):
            assert ("adds about" in line) == d.raises
            assert ("reduces value by about" in line) != d.raises


def test_display_value_gates_and_formats_for_residents():
    from philly_assessments.models.explain import display_value

    # self-explanatory facts get human formatting with units
    assert display_value("char_livable_area", 1120.0) == "1,120 sq ft"
    assert display_value("char_beds", 3.0) == "3 beds"
    # a year is not a quantity — no thousands separator
    assert display_value("char_year_built", 1750.0) == "1750"
    # model-internal values (log surfaces, encoded geography) are suppressed
    assert display_value("mkt_knn_log_ppsf", 6.2306) is None
    assert display_value("loc_census_tract_raw", 1.0) is None
    assert display_value("char_livable_area", None) is None
