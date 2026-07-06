import numpy as np

from philly_fair_measure.diagnostics.channel import (
    CHANNEL_DISCOUNT_BY_QUINTILE,
    cash_market_value,
)


def test_cash_market_value_applies_tiered_discount():
    edges = [100_000.0, 200_000.0, 300_000.0, 400_000.0]
    retail = np.array([80_000.0, 150_000.0, 250_000.0, 350_000.0, 500_000.0])
    cash = cash_market_value(retail, edges)
    # cheapest tier gets the deepest discount, priciest the shallowest
    assert cash[0] == retail[0] * (1 + CHANNEL_DISCOUNT_BY_QUINTILE[0])
    assert cash[-1] == retail[-1] * (1 + CHANNEL_DISCOUNT_BY_QUINTILE[4])
    # cash-market value is always below retail (discounts are negative)
    assert (cash < retail).all()
    # monotone discount: cheap tier discounted more than expensive
    assert (retail[0] - cash[0]) / retail[0] > (retail[-1] - cash[-1]) / retail[-1]
