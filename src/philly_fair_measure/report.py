"""Staff worklists from the assessment screen.

`leaderboards` lists the most over- and under-assessed flagged properties and
the least uniform blocks of identical homes. `fair-measure leaderboard` prints
them, and `/api/admin/leaderboard` serves them.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from philly_fair_measure import config
from philly_fair_measure.vocab import AssessmentFlag

_MIN_TWINS = 5  # only blocks with this many identical homes count for uniformity
# The model's own 90% interval spanning more than this (pi_high / pi_low) means it
# has no real opinion of the property — the residential model can't value it (e.g.
# a Navy Yard parcel, interval ~119x). p99 of flagged candidates is ~12x, so 10x
# drops the top ~2.4% of blind spots. Kept properties rank by screen_z, the
# OPA-vs-model gap in units of the model's own predictive uncertainty (which a raw
# ratio ignores) — the same measure the screen itself sorts on.
_MAX_INTERVAL_WIDTH = 10.0


def leaderboards(
    data_dir: Path | None = None, *, n: int = 25, plausible: bool = True
) -> dict[str, pl.DataFrame]:
    """Review/appeal worklists from the assessment screen: the most over- and
    under-assessed flagged properties (OPA vs model, dual-model-gated) and the
    least-uniform blocks (a home vs its identical twins' median). By default the
    over/under lists drop properties the model can't value (its 90% interval spans
    > _MAX_INTERVAL_WIDTH) and rank the rest by screen_z, so the model's blind
    spots don't crowd out — and its confidence isn't ignored on — ordinary appeal
    targets. Pass plausible=False for the raw biggest-ratio extremes (blind spots
    included). Verify any single row against its report, which surfaces data
    errors. Rows show the displayed estimate (display_median, display_ratio),
    the number the property page shows, and the extremes rank by that ratio; the
    blind-spot filter and screen_z stay on the Bayesian machine that gates the
    flags."""
    root = data_dir if data_dir is not None else config.data_dir()
    s = (
        pl.read_parquet(root / "marts" / "assessment_screen.parquet")
        .filter((pl.col("opa_market_value") > 30_000) & (pl.col("model_median") > 30_000))
        .with_columns(
            (pl.col("model_pi_high_90") / pl.col("model_pi_low_90")).alias("interval_width")
        )
    )
    cols = [
        "parcel_id",
        "address",
        "opa_market_value",
        "display_median",
        "display_ratio",
        "screen_z",
    ]
    over_flagged = s.filter(pl.col("assessment_flag") == AssessmentFlag.OVER)
    under_flagged = s.filter(pl.col("assessment_flag") == AssessmentFlag.UNDER)
    if plausible:  # keep what the model has a real opinion about, rank by screen_z
        keep = pl.col("interval_width") <= _MAX_INTERVAL_WIDTH
        over_flagged = over_flagged.filter(keep).sort("screen_z", descending=True)
        under_flagged = under_flagged.filter(keep).sort("screen_z")
    else:  # raw biggest-disagreement extremes, blind spots included
        over_flagged = over_flagged.sort("display_ratio", descending=True)
        under_flagged = under_flagged.sort("display_ratio")
    over = over_flagged.head(n).select(cols)
    under = under_flagged.head(n).select(cols)
    non_uniform = (
        s.filter((pl.col("twin_n") >= _MIN_TWINS) & pl.col("opa_vs_twin_median").is_not_null())
        .with_columns((pl.col("opa_vs_twin_median") - 1.0).abs().alias("twin_gap"))
        .sort("twin_gap", descending=True)
        .head(n)
        .select(
            "parcel_id",
            "address",
            "opa_market_value",
            "display_median",
            "twin_n",
            "opa_vs_twin_median",
        )
    )
    return {"over_assessed": over, "under_assessed": under, "non_uniform_block": non_uniform}
