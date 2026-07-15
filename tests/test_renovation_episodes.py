from datetime import datetime

import polars as pl

from philly_fair_measure.features.renovation_episodes import (
    add_current_renovation_episode_features,
    add_renovation_episode_features,
)
from philly_fair_measure.models.renovation_state import (
    PROBABILITY_INPUTS,
    TRANSITION_CROSSFIT_FILE,
    TRANSITION_METADATA_FILE,
    TRANSITION_MODEL_FILE,
    add_persisted_transition_probability,
)


def test_episode_features_use_only_permits_strictly_between_sales():
    sales = pl.DataFrame(
        {
            # One transfer may contain several parcels, so sale_id alone is
            # not a safe event-join key.
            "sale_id": ["a1", "shared", "b1", "shared"],
            "parcel_id": ["a", "a", "b", "b"],
            "sale_date": [
                datetime(2020, 1, 1),
                datetime(2021, 1, 1),
                datetime(2020, 1, 1),
                datetime(2021, 1, 1),
            ],
            "sale_price": [100_000.0, 180_000.0, 100_000.0, 180_000.0],
            "time_adj_log": [0.0, 0.0, 0.0, 0.0],
        }
    )
    permits = pl.DataFrame(
        {
            "opa_account_num": ["a", "a", "a", "a", "b"],
            "permitissuedate_parsed": [
                datetime(2019, 12, 1),  # before acquisition
                datetime(2020, 3, 1),  # included completed alteration
                datetime(2020, 6, 1),  # included active trade permit
                datetime(2021, 1, 1),  # same day as resale, excluded
                datetime(2021, 2, 1),  # after resale, excluded
            ],
            "permitcompleteddate_parsed": [
                None,
                datetime(2020, 11, 1),
                None,
                None,
                None,
            ],
            "certificateofoccupancydate_parsed": [None] * 5,
            "typeofwork": ["MAJOR", "Addition and/or Alteration", "EZ PLUMBING", "MAJOR", "MAJOR"],
        }
    )

    episodes = add_renovation_episode_features(sales, permits)
    assert episodes["sale_id"].to_list() == sales["sale_id"].to_list()
    assert episodes["parcel_id"].to_list() == sales["parcel_id"].to_list()
    by_id = {(row["sale_id"], row["parcel_id"]): row for row in episodes.to_dicts()}
    resale = by_id[("shared", "a")]
    assert resale["episode_eligible"] == 1.0
    assert resale["episode_permits_since_acquisition"] == 2.0
    assert resale["episode_reno_permits_since_acquisition"] == 1.0
    assert resale["episode_other_permits_since_acquisition"] == 1.0
    assert resale["episode_completed_reno_since_acquisition"] == 1.0
    assert resale["episode_active_permits_since_acquisition"] == 1.0
    assert resale["episode_high_recovery_label"] == 1
    assert resale["episode_permit_confirmed_label"] == 1
    assert by_id[("shared", "b")]["episode_permits_since_acquisition"] == 0.0
    assert by_id[("shared", "b")]["episode_permit_confirmed_label"] == 0


def test_probability_inputs_exclude_targets_and_assessments():
    forbidden = {
        "sale_price",
        "fin_cash_sale",
        "asmt_market_value_sale_year",
        "episode_recovery_log",
        "episode_high_recovery_label",
        "episode_permit_confirmed_label",
    }
    assert forbidden.isdisjoint(PROBABILITY_INPUTS)


def test_current_episode_features_stop_at_valuation_date_and_have_no_outcome_label():
    current = pl.DataFrame(
        {
            "parcel_id": ["a"],
            "last_sale_date": [datetime(2020, 1, 1)],
            "mkt_parcel_prev_log_price_ref": [11.5],
            "mkt_knn_price_anchor_log": [12.0],
        }
    )
    permits = pl.DataFrame(
        {
            "opa_account_num": ["a", "a", "a"],
            "permitissuedate_parsed": [
                datetime(2019, 12, 1),
                datetime(2020, 3, 1),
                datetime(2021, 1, 1),
            ],
            "permitcompleteddate_parsed": [None, datetime(2020, 11, 1), None],
            "certificateofoccupancydate_parsed": [None, None, None],
            "typeofwork": ["MAJOR", "Addition and/or Alteration", "MAJOR"],
        }
    )
    out = add_current_renovation_episode_features(current, permits, datetime(2021, 1, 1))
    row = out.row(0, named=True)
    assert row["episode_eligible"] == 1.0
    assert row["episode_permits_since_acquisition"] == 1.0
    assert row["episode_completed_reno_since_acquisition"] == 1.0
    assert row["episode_prior_discount_log"] == 0.5
    assert "episode_high_recovery_label" not in out.columns
    assert "episode_recovery_log" not in out.columns


def test_historical_scoring_reuses_cross_fitted_probability(tmp_path):
    # Dummy model files prove a fully matched historical row returns from the
    # lookup path without loading/recomputing the final classifier.
    (tmp_path / TRANSITION_METADATA_FILE).write_text("{}")
    (tmp_path / TRANSITION_MODEL_FILE).write_text("not a model")
    pl.DataFrame(
        {
            "sale_id": ["s"],
            "parcel_id": ["p"],
            "sale_date": [datetime(2024, 1, 1)],
            "episode_transition_probability": [0.37],
        }
    ).write_parquet(tmp_path / TRANSITION_CROSSFIT_FILE)
    row = pl.DataFrame(
        {
            "sale_id": ["s"],
            "parcel_id": ["p"],
            "sale_date": [datetime(2024, 1, 1)],
        }
    )
    out = add_persisted_transition_probability(tmp_path, row)
    assert out["episode_transition_probability"].to_list() == [0.37]
