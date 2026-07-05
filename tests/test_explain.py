import numpy as np


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
