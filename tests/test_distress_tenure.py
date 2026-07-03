from datetime import datetime

import polars as pl

from philly_assessments.features.sale_features import (
    DISTRESS_TENURE_COLUMNS,
    distress_tenure_features,
)


def _targets():
    return pl.DataFrame(
        {
            "sale_id": ["s1", "s2"],
            "parcel_id": ["p1", "p2"],
            "sale_date": [datetime(2023, 6, 1), datetime(2023, 6, 1)],
        }
    )


def test_complaint_windows_and_no_future_leakage():
    complaints = pl.LazyFrame(
        [
            # in-window interior + vacancy for p1
            {"opa_account_num": "p1", "complaintdate_parsed": datetime(2022, 6, 1),
             "complaintcodename": "MAINTENANCE RESIDENTIAL"},
            {"opa_account_num": "p1", "complaintdate_parsed": datetime(2021, 6, 1),
             "complaintcodename": "VACANT HOUSE"},
            # outside the 5y window: counts in nothing but days_since ignores it too
            # (vacancy recency looks at all strictly-prior events)
            {"opa_account_num": "p1", "complaintdate_parsed": datetime(2010, 1, 1),
             "complaintcodename": "VACANT HOUSE"},
            # FUTURE complaint must never count
            {"opa_account_num": "p1", "complaintdate_parsed": datetime(2024, 1, 1),
             "complaintcodename": "MAINTENANCE RESIDENTIAL"},
            # exterior for p2, plus modern-vocabulary interior + unpermitted work
            {"opa_account_num": "p2", "complaintdate_parsed": datetime(2023, 1, 1),
             "complaintcodename": "PROPERTY MAINTENANCE HIGH WEEDS"},
            {"opa_account_num": "p2", "complaintdate_parsed": datetime(2023, 2, 1),
             "complaintcodename": "PROPERTY MAINTENANCE COMPLAINT INTERIOR"},
            {"opa_account_num": "p2", "complaintdate_parsed": datetime(2023, 3, 1),
             "complaintcodename": "WORK UNDERWAY WITHOUT PERMITS"},
        ]
    )
    out = distress_tenure_features(_targets(), complaints=complaints)
    by = {r["sale_id"]: r for r in out.to_dicts()}
    assert by["s1"]["evt_n_int_maint_complaints_5y_before"] == 1
    assert by["s1"]["evt_n_vacant_complaints_5y_before"] == 1
    assert by["s1"]["evt_n_complaints_5y_before"] == 2  # future + stale excluded
    assert by["s1"]["evt_vacant_complaint_days_since"] == 730  # most recent vacancy
    assert by["s2"]["evt_n_ext_maint_complaints_5y_before"] == 1
    # both vocabulary eras count (the legacy-only lists zeroed out post-2022)
    assert by["s2"]["evt_n_int_maint_complaints_5y_before"] == 1
    assert by["s2"]["evt_n_unpermitted_work_complaints_5y_before"] == 1
    assert by["s2"]["evt_n_vacant_complaints_5y_before"] == 0  # has events, none vacant


def test_rental_license_spans_at_sale_date():
    licenses = pl.LazyFrame(
        [
            # active at sale (open-ended)
            {"opa_account_num": "p1", "initialissuedate_parsed": datetime(2020, 1, 1),
             "inactivedate_parsed": None, "owneroccupied": "No", "numberofunits": 2},
            # ended before the sale: must not count
            {"opa_account_num": "p2", "initialissuedate_parsed": datetime(2015, 1, 1),
             "inactivedate_parsed": datetime(2020, 1, 1), "owneroccupied": "No",
             "numberofunits": 1},
        ]
    )
    out = distress_tenure_features(_targets(), rental_licenses=licenses)
    by = {r["sale_id"]: r for r in out.to_dicts()}
    assert by["s1"]["ten_rental_license_at_sale"] == 1.0
    assert by["s1"]["ten_owner_occupied_rental"] == 0.0
    assert by["s1"]["ten_rental_units"] == 2.0
    assert by["s2"]["ten_rental_license_at_sale"] is None  # lapsed -> no active license


def test_investigations_appeals_and_stable_schema():
    investigations = pl.LazyFrame(
        [
            {"opa_account_num": "p1", "investigationcompleted_parsed": datetime(2022, 1, 1),
             "investigationtype": "PRECOURT"},
            {"opa_account_num": "p1", "investigationcompleted_parsed": datetime(2022, 2, 1),
             "investigationtype": "HCEU INSP"},
        ]
    )
    appeals = pl.LazyFrame(
        [
            {"opa_account_num": "p1", "decisiondate_parsed": datetime(2019, 1, 1),
             "appealtype": "ZBA Permit Denial - Variance", "decision": "GRANTED"},
            {"opa_account_num": "p1", "decisiondate_parsed": datetime(2020, 1, 1),
             "appealtype": "ZBA Permit Denial - Variance", "decision": "DENIED"},
            {"opa_account_num": "p1", "decisiondate_parsed": datetime(2021, 1, 1),
             "appealtype": "LIRB Violation Appeal", "decision": "GRANTED"},
        ]
    )
    out = distress_tenure_features(_targets(), investigations=investigations, appeals=appeals)
    by = {r["sale_id"]: r for r in out.to_dicts()}
    assert by["s1"]["evt_n_investigations_5y_before"] == 2
    assert by["s1"]["evt_n_precourt_5y_before"] == 1
    # grants from any board count (decision vocab is split across system
    # generations); denials don't
    assert by["s1"]["evt_n_appeal_granted_before"] == 2

    # all-None inputs still yield the full stable schema
    empty = distress_tenure_features(_targets())
    assert set(DISTRESS_TENURE_COLUMNS) <= set(empty.columns)
