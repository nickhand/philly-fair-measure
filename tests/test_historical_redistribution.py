from datetime import datetime

import numpy as np
import polars as pl

from philly_fair_measure.diagnostics.historical_redistribution import (
    _tier_redistribution,
    historical_redistribution,
)


def test_uniform_assessment_is_neutral():
    rng = np.random.default_rng(0)
    value = rng.uniform(50_000, 500_000, 1000)
    opa = 0.9 * value  # every home at the same ratio -> no redistribution
    bottom, q1q5, med = _tier_redistribution(opa, value)
    assert abs(bottom) < 1e-9
    assert abs(q1q5 - 1.0) < 1e-9
    assert abs(med - 0.9) < 1e-9


def test_flat_assessment_is_regressive():
    value = np.linspace(50_000, 500_000, 1000)
    opa = np.full(1000, 200_000.0)  # everyone assessed the same -> steeply regressive
    bottom, q1q5, med = _tier_redistribution(opa, value)
    assert bottom > 0  # the cheap bottom overpays
    assert q1q5 > 1.0  # q1 ratio exceeds q5 ratio (the definition of regressive)


def test_end_to_end_derives_the_partial_year(tmp_path):
    """The full pipeline runs against a synthetic data dir, and the latest sale
    year is flagged partial when its records stop before December (the old
    hardcoded year went stale every January — and an unaliased duplicate
    projection here once crashed export-web-stats)."""
    rng = np.random.default_rng(1)
    n = 600
    rows = []
    for year, month in ((2030, 12), (2031, 6)):  # 2031 records stop in June
        price = rng.uniform(50_000, 900_000, n)
        rows.append(
            pl.DataFrame(
                {
                    "parcel_id": [f"{year}{i:05d}" for i in range(n)],
                    "sale_date": [datetime(year, 1 + i % month, 1 + i % 28) for i in range(n)],
                    "sale_price": price,
                    "asmt_market_value_sale_year": price * 0.9,
                    "fin_cash_sale": [float(i % 3 == 0) for i in range(n)],
                }
            )
        )
    (tmp_path / "marts").mkdir()
    (tmp_path / "staged").mkdir()
    pl.concat(rows).write_parquet(tmp_path / "marts" / "sale_features.parquet")
    pl.DataFrame(
        {
            "parcel_number": ["203000000"],
            "category_code_description": ["SINGLE FAMILY"],
        }
    ).write_parquet(tmp_path / "staged" / "opa_properties.parquet")
    pl.DataFrame(
        {
            "parcel_number": ["203000000", "203000000"],
            "year_parsed": [2030, 2031],
            "market_value": [200_000.0, 210_000.0],
        }
    ).write_parquet(tmp_path / "staged" / "assessments.parquet")

    out = historical_redistribution(tmp_path)
    flags = {int(r["year"]): bool(r["partial_year"]) for r in out.to_dicts()}
    assert flags == {2030: False, 2031: True}
