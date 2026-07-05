# What OPA's regressive assessments cost, 2016–2025

How much property tax did Philadelphia's regressive assessments shift, per year,
in dollars — and to whom. The short version: **the burden shifted by property
value is real and adds up to roughly a third of a billion dollars over the
decade; the burden shifted by race runs the *opposite* of the intuitive story.**

Reproduce with `historical_redistribution()` and `redistribution_by_race()` in
`diagnostics/historical_redistribution.py`.

## What "cost" means here

Property tax is **revenue-neutral**: the city picks a millage to hit a target
levy, so a "bad model" doesn't make revenue vanish — it **redistributes** the
burden. Every dollar the bottom over-pays, the top under-pays. So the honest
quantity is "how much burden was shifted," not "how much the city lost."

**Method.** A sold-home ratio study using *actual sales* as market truth (not
our model — we have no as-of features for 2016). For each year we compare OPA's
roll to a uniform-ratio "fair" roll, and extrapolate the bottom-40%'s net
over-assessment (a share of the levy) to the full residential roll × the flat
**1.3998%** millage (constant 2016–2027; only the city/school split moved, in
2025). Two benchmarks for market value, because the choice roughly doubles the
answer:

- **Financed** — financed sales only, the defensible IAAO-style sample.
- **Raw sale** — all arms-length sales, cash-inflated on the low end.

Coverage: 2016–2025 full, 2026 partial (sales still accruing), **2027 impossible**
(no sales under that roll yet). Tax is on gross assessed value; the homestead
exemption ($30k→$100k over the period, mildly progressive) would modestly shrink
the bottom's overpayment and is noted, not modelled.

## Card 1 — burden shifted from lower- to higher-value homes

Bottom-40% (by value) net **over**-payment; the top-60% under-paid the same.

| Year | q1/q5 regressivity | Financed: shifted | per resident | Raw-sale: shifted |
|---|---|---|---|---|
| 2016 | 1.56 | $55M | $35 | $82M |
| 2017 | 1.54 | $59M | $38 | $78M |
| 2018 | 1.53 | $57M | $36 | $78M |
| 2019 | 1.20 | $30M | $19 | $56M |
| 2020 | 1.05 | $15M | $10 | $40M |
| 2021 | 0.93 | $1M | $1 | $22M |
| 2022 | 0.95 | −$2M | −$1 | $27M |
| 2023 | 1.21 | $38M | $24 | $81M |
| 2024 | 1.19 | $38M | $24 | $77M |
| 2025 | 1.38 | $64M | $41 | $108M |
| **2016–2025 total** | | **≈ $357M** | **≈ $226** | **≈ $650M** |

*(2026, partial: financed $80M.)* Concentrated on the ~186k homes in the bottom
two quintiles, the financed figure is on the order of **$300–350 per
lower-value home in the regressive years**.

**The shape tells a policy story — but the 2020–22 dip is a trap, not a fix.**
Regressivity was worst in the **pre-reform years (2016–18)** and has climbed back
since the 2023 reassessment. The near-zero **2020–22** stretch is *not* the freeze
making assessments fairer: the freeze locked the TY2020 roll while the market
boomed, so rising sale prices pulled every assessed/sale ratio down (the median
hit **0.63** by 2022 — everyone under-assessed relative to current prices), and
the previously *over*-assessed cheap end was **absorbed by appreciation**, which
masked the regressivity and briefly inverted it. It snapped right back at the
2023 reassessment, and a freeze during a *falling* market would have made it
worse. So the harm tracks *assessment practice*, but a rising market can
temporarily hide it.

## Card 2 — by race, the intuitive story reverses

Net over/under-payment by **tract majority race**, financed sample, % of levy
(+ = that group's neighborhoods over-paid):

| Year | Black-majority tracts | White-majority tracts | Hispanic-majority |
|---|---|---|---|
| 2016 | −0.3% | −0.5% | +1.0% |
| 2018 | **−2.2%** | **+1.7%** | +0.7% |
| 2020 | **−4.0%** | **+4.8%** | −0.6% |
| 2022 | **−4.6%** | **+5.9%** | −1.3% |
| 2024 | −1.1% | +1.6% | −0.6% |
| 2025 | −0.3% | +0.5% | −0.2% |

**Every year for a decade, Black-majority tracts net *under*-paid and
White-majority tracts over-paid** on the defensible sample — the opposite of
"regressive assessments overtaxed Black homeowners." The mechanism is value
composition, not race-targeting: the homes that sell *financed* in Black
neighborhoods skew to the higher-value end that regressivity *under*-assesses.

The naive claim survives only on the **raw-sale** benchmark, and only as a
**cash-market artifact**: homes in disinvested neighborhoods sell cash-cheap, so
OPA *looks* like it over-assesses them relative to those depressed prices — but
that's the exact cash trap the IAAO standard excludes, and it evaporates (indeed
reverses) on financed sales.

## The honest reading

- **The defensible, damning number is by value:** ~$357M (financed) to ~$650M
  (raw) of tax burden shifted from lower- to higher-value homes over 2016–2025,
  worst before the reforms.
- **Do not publish a "cost to Black homeowners" figure.** On the sample the
  assessment standard is built on, it reverses, consistently. If a racial harm
  exists it lives in the **cash-market / unrealizable-value** argument (homes
  taxed above what they can actually fetch), which is a different and harder
  claim than a ratio study — see [report-assessment-equity.md](report-assessment-equity.md).
- **Caveats that keep it honest:** the race cut is ecological (tract, not
  person) and on sold financed homes; the citywide dollar figures extrapolate a
  sold-sample share to the full roll (assumes sold homes represent their tier);
  and they're gross of the homestead exemption. The per-year *shares* are the
  robust part; the dollar totals are order-of-magnitude.

See the [vertical-equity report card](vertical-equity-report-card.md) for the
single-year cross-section this puts in motion.
