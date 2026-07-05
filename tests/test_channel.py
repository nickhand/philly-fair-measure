import numpy as np
import polars as pl

from philly_assessments.diagnostics.channel import _design, _ols_coef


def test_design_recovers_planted_channel_discount():
    # plant: value driven by area + district; cash sells 12% lower (pure
    # channel), and cash is CORRELATED with a distress signal that itself
    # lowers value 20% — a naive raw gap overstates the channel discount
    rng = np.random.default_rng(0)
    n = 6000
    district = rng.integers(0, 4, n).astype(str)
    area = rng.uniform(800, 2500, n)
    distressed = rng.random(n) < 0.3
    # cash sales oversample distressed houses (selection)
    is_cash = ((rng.random(n) < 0.25) | (distressed & (rng.random(n) < 0.5))).astype(float)
    log_value = (
        11.0
        + 0.0004 * area
        + district.astype(float) * 0.1
        - 0.20 * distressed  # distress lowers true value
        - 0.12 * is_cash  # pure channel discount
        + rng.normal(0, 0.05, n)
    )
    df = pl.DataFrame(
        {
            "loc_district": ["d" + d for d in district],
            "char_livable_area": area,
            "char_beds": rng.integers(2, 5, n).astype(float),
            "char_baths": np.ones(n),
            "char_year_built": np.full(n, 1925.0),
            "mkt_knn_log_ppsf": rng.normal(5.0, 0.1, n),
            "mkt_area_level_log_ppsf": np.zeros(n),
            "char_style": ["row"] * n,
            "char_exterior_condition": ["4"] * n,
            "char_interior_condition": ["4"] * n,
            "dist_tax_delinquent": distressed.astype(float),
            "dist_sheriff_sale": np.zeros(n),
            "evt_n_vacant_complaints_5y_before": distressed.astype(float),
            "evt_n_unpermitted_work_complaints_5y_before": np.zeros(n),
            "evt_n_severe_violations_5y_before": np.zeros(n),
            "evt_n_open_severe_at_sale": np.zeros(n),
            "fin_cash_sale": is_cash,
        }
    )

    def cash_pct(stage):
        x, ix = _design(df, stage)
        return (
            float(np.exp(_ols_coef(log_value, log_value * 0 + log_value, ix)) - 1)
            if False
            else float(np.exp(_ols_coef(x, log_value, ix)) - 1)
        )

    raw = cash_pct("raw")
    pure = cash_pct("distress")
    # raw gap is inflated by the distress correlation; controlling for distress
    # recovers the planted -12% pure channel discount
    assert raw < pure  # raw more negative (overstates)
    assert -0.16 < pure < -0.08  # recovers ~-12%
