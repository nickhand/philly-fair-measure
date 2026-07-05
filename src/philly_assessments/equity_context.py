"""Per-property equity context: the regressivity finding made personal.

Where a home's assessment sits relative to genuinely comparable homes — same
neighborhood (ZIP) and similar value. It compares the property's OPA / estimated-
market-value ratio to the median ratio of its peers.

Why this is defensible even though "market value" is the model's estimate: it's
a **relative** comparison. Both the home and its peers are divided by the same
model, so a uniform level bias in the model cancels — "your ratio is higher than
your neighbors'" is a valid horizontal-inequity signal as long as the model is
not *differentially* biased within the peer group. The panel says "estimated
market value" and never claims the ratio proves unfairness on its own; the
aggregate ratio studies (docs/report-assessment-equity.md) carry that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from philly_assessments import config
from philly_assessments.scalars import as_float

logger = logging.getLogger(__name__)

_MIN_PEERS = 40
_VALUE_BAND = 1.5  # peers within value/1.5 .. value*1.5 of this home's estimate
_IN_LINE = 0.05  # within +/- 5% of the peer median reads as "in line"


@dataclass(frozen=True)
class EquityContext:
    ratio: float  # this home's OPA / estimated market value
    peer_median_ratio: float
    peer_n: int
    percentile: float  # share of peers assessed at a lower ratio than this home (0-100)
    peer_label: str
    verdict: str  # "over" | "under" | "in line"

    @property
    def over_assessed(self) -> bool:
        return self.verdict == "over"


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def equity_context(
    screen_row: dict[str, object], data_dir: Path | None = None, *, min_peers: int = _MIN_PEERS
) -> EquityContext | None:
    """Peer-relative equity context for one property, or None if it lacks a
    ratio or has too few comparable homes even after the neighborhood fallback."""
    ratio = _num(screen_row.get("opa_vs_model_ratio"))
    model = _num(screen_row.get("model_median"))
    if ratio is None or model is None or model <= 0:
        return None

    root = data_dir if data_dir is not None else config.data_dir()
    parcel_id = screen_row.get("parcel_id")
    zip5 = screen_row.get("loc_zip5")
    res = pl.scan_parquet(root / "marts" / "assessment_screen.parquet").filter(
        (pl.col("model_family") == "residential")
        & (pl.col("opa_market_value") > 0)
        & (pl.col("model_median") > 0)
        & (pl.col("opa_vs_model_ratio").is_not_null())
        & (pl.col("parcel_id") != parcel_id)
    )
    if zip5 is not None:
        res = res.filter(pl.col("loc_zip5") == zip5)
    lo, hi = model / _VALUE_BAND, model * _VALUE_BAND

    band = (
        res.filter(pl.col("model_median").is_between(lo, hi))
        .select("opa_vs_model_ratio")
        .collect()
    )
    if band.height >= min_peers:
        peers, scope = band, "similar value"
    else:  # thin tier — fall back to the whole neighborhood
        neighborhood = res.select("opa_vs_model_ratio").collect()
        if neighborhood.height < min_peers:
            return None
        peers, scope = neighborhood, "all values"

    peer_ratios = peers["opa_vs_model_ratio"]
    peer_median = as_float(peer_ratios.median())
    percentile = as_float((peer_ratios < ratio).mean()) * 100.0
    if ratio > peer_median * (1 + _IN_LINE):
        verdict = "over"
    elif ratio < peer_median * (1 - _IN_LINE):
        verdict = "under"
    else:
        verdict = "in line"

    where = f"ZIP {zip5}, {scope}" if zip5 is not None else scope
    return EquityContext(ratio, peer_median, peers.height, percentile, where, verdict)
