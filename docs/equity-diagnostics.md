# Equity Diagnostics: Assessment Ratios by Tract Racial Composition

*Working notes. The polished, externally-oriented synthesis of these findings
is [report-assessment-equity.md](report-assessment-equity.md) — the version to
share with the Controller's office, Council, or press.*

Run 2026-07-03, prompted by the City Controller's
[property assessment review](https://controller.phila.gov/philadelphia-reports/property-assessment-review/)
(which found OPA's 2014–2019 assessments regressive and least uniform in
low-income West/North/Southwest Philadelphia) and related reporting that
framed the same pattern racially.

**Method.** 202,587 validated arms-length residential sales (condo-excluded)
spatially joined to 2020 census tracts; tract racial composition and the
majority-race classification from the city-published ACS 2022 tract layer
(both snapshotted with manifests: `census_tracts_2020`,
`acs_tract_demographics`). Ratio = OPA market value for the sale year ÷
subsequent sale price (raw out-of-time convention; levels shift under other
conventions but between-group *gaps* are robust). COD/PRD via assesspy.

**Demographics are used only in this diagnostic** — never as valuation
features — matching both OPA's legal constraint and this project's design.
Tract-level analysis is ecological: it describes places, not individual owners.

## Controller era (2016–2019 sales, n=83,240)

| Group | n | median ratio | COD | PRD |
|---|---|---|---|---|
| Majority-White tracts | 37,641 | **0.840** | 29.2 | 1.152 |
| Majority-Black tracts | 34,876 | **0.937** | **63.1** | **1.479** |
| Majority-Hispanic tracts | 10,117 | **1.011** | 53.8 | 1.323 |
| pct-white Q1 (0–7%) | 20,686 | **1.099** | 60.6 | 1.383 |
| pct-white Q4 (61–100%) | 20,940 | **0.836** | 27.1 | 1.141 |

The least-white quartile of tracts was assessed **above** market value at the
median (1.10) while the whitest quartile sat 16% **below** (0.84) — a 26-point
monotonic gradient — with uniformity more than twice as bad (COD 61 vs 27) and
far stronger within-group regressivity. **This strongly supports the
Controller-era conclusions on both the income and racial framings.**

## Current era (2023+ sales vs post-TY23 rolls, n=54,400)

| Group | n | median ratio | COD | PRD |
|---|---|---|---|---|
| Majority-White tracts | 22,542 | 0.886 | 23.5 | 1.084 |
| Majority-Black tracts | 24,234 | 0.937 | 45.9 | 1.228 |
| Majority-Hispanic tracts | 7,224 | 0.942 | 47.4 | 1.270 |
| pct-white Q1 (0–5%) | 13,529 | 0.967 | 50.7 | 1.283 |
| pct-white Q4 (61–100%) | 13,680 | 0.880 | 22.2 | 1.081 |

The reassessments since TY2023 **substantially narrowed** the gap (26 → ~9
ratio points between extreme quartiles) — consistent with OPA's claimed
year-over-year improvement — but did **not eliminate it**: majority-Black and
Hispanic tracts remain assessed ~5–6 points higher relative to market value
than majority-White tracts, at roughly double the dispersion.

## Is the gap inevitable? No — our model nearly eliminates it

On the identical out-of-time test sales (n=19,464), the same-group median
ratios and dispersion:

| Group | OPA median | Model median | OPA COD | Model COD |
|---|---|---|---|---|
| Majority-White tracts | 0.948 | 0.992 | 20.6 | 17.6 |
| Majority-Black tracts | 1.035 | 0.988 | 42.7 | 32.9 |
| Majority-Hispanic tracts | 1.021 | 0.954 | 43.9 | 32.9 |

OPA's 8.7-point White/Black median-ratio gap collapses to **0.4 points** under
the public-data-only model (which contains no demographic features). Dispersion
in minority tracts remains higher for both — cheap-tail sales are noisier for
everyone (see the q1 analysis in feature-plan-v2.md) — but the *systematic
level bias by racial composition is a modeling artifact, not a data
inevitability*. This mirrors the national finding (arXiv:2605.15020) that
better models improve accuracy and equity together.

## The condo contrast (added 2026-07-03, corrected same day)

A between-segment asymmetry complements the tract-level story. After the
condo deed-link recovery (see docs/features.md — the earlier "OPA assesses
condos at 75% of sale price" figure is **retracted**; it was measured on a
contaminated pool of bulk building sales), the honest comparison on true
condo units is:

| Segment | OPA median ratio | OPA COD |
|---|---|---|
| Residential condo units (test, n=2,802) | 0.91 | 18.8 |
| All non-condo residential (test, n=19,463) | 0.98 | 34.5 |

Condos — an affluent-skewing, heavily Center City stock — are OPA's
best-assessed segment: accurate, tight, and slightly *under* market. Cheap
rowhomes — disproportionately in majority-Black and majority-Hispanic
tracts — get dispersed, regressive assessments (cheapest-quintile median
ratios above 1.2 in the Controller era). The equity problem is not that OPA
can't assess accurately; it's that its accuracy is distributed along lines
that track wealth and race.

## What would the banned features buy? Nothing (measured 2026-07-03)

`philly acs-sensitivity` retrains the residential LightGBM with tract ACS
aggregates (racial shares, median income, poverty rate) as features, on the
identical split/params/seed — a diagnostic only; the augmented model is never
persisted or used. Result: ACS features carry **1.15% of total gain**;
overall RMSE(log) 0.3402 → 0.3410 (a hair *worse*), COD unchanged
(26.286 → 26.284), q1 unimproved, and no majority-race group's ratio or COD
moves by more than noise (Black-tract COD 32.8 → 32.9, White-tract
17.60 → 17.56). The learned spatial machinery (kNN sale surface, market
areas, block rolls) already subsumes whatever tract demographics would
proxy. **The legal ban on people-data costs nothing** — accuracy and legal
parity are not in tension here, which strengthens the civic version of this
argument: there is no accuracy excuse for demographic-correlated assessment
error. (Artifact: `data/diagnostics/acs_sensitivity.parquet`.)

## The cash/financed bifurcation — the rebuttal, pre-empted (2026-07-04)

The sharpest attack on any "OPA over-assesses cheap homes" finding is: *cheap
homes really do sell for less, so of course the ratio looks high.* We
measured whether that rebuttal holds (`philly channel-decomp`, an OLS of
reference-frame log price with sequential controls; diagnostic only).

**~40% of Philadelphia arms-length sales are cash, and the discount survives
every observable control.** The raw within-district cash discount is −43.6%;
controlling for house composition (area, beds, condition, style, ...) takes
it to −30.0%; adding the full distress stack (delinquency, vacancy,
unpermitted work, severe violations) barely moves it to **−29.4%** (bootstrap
95% CI [−29.7%, −29.1%]). Distress explains almost none of it. The cleaner
within-price-tier estimates (which absorb residual value confounding the
pooled model can't): pure channel discount **−21.6% in the cheapest quintile,
falling to −2.7% in the most expensive** — the cash/wholesale market
dominates exactly the cheap tail. Distress *amplifies* the discount rather
than explaining it (clean house −27.6% vs distressed −36.4%): distressed +
cash is the deep-discount investor-flip market, not merely "shells worth
less."

**What this does to the regressivity finding — the honest, nuanced version:**
this cuts both ways, and the nuance is the contribution.

- It **validates** a retail-value model (the channel discount is real, large,
  and well-identified — adjusting cash sales up to typical-financing value is
  warranted).
- It **partially defends OPA** on the narrow point: measured against *cash
  sale prices*, OPA's cheap-tail ratio looks regressive (~1.2), but a q1 house
  selling $100k cash has a retail value nearer $128k, so OPA's ~$120k
  assessment is *below* retail — not over-assessment against the legal
  standard.
- It **relocates the real regressivity** to a deeper place: low-income owners
  in bifurcated neighborhoods are taxed on a retail value they often *cannot
  realize*, because the only buyers for their block are cash investors. Taxing
  a fictional retail value in a market where the owner is structurally stuck in
  the cash tier is its own regressivity — and a policy-standard question (is
  "typical-financing market value" even the right basis in a bifurcated
  market?), not a modeling error.

The Controller-era finding stands, but the mechanism is richer than "OPA is
wrong": it is a bifurcated-market and assessment-standard problem. Reporting
the ratio against **both** cash-sale and retail-value conventions (as we
report both out-of-time and TASP time conventions) is what makes the analysis
un-dismissable. Artifact: `data/diagnostics/channel_decomposition.parquet`.

### The retail model and the both-conventions ratio study (`philly retail-market`)

We built the retail predictor (train the LightGBM on mortgage-financed sales
only — the transactions that ARE the typical-financing standard) and verified
it behaves: on financed test sales it matches the blend model (COD 21.4 vs
21.1, median ratio 0.984 — near-unbiased on the retail market), and on cash
sales it predicts **21% above the cash sale price** (ratio 1.213), correctly
recovering retail value for houses that transacted wholesale. (Its "overall"
COD looks worse only because half the test *actuals* are cash prices it
intentionally does not target; the retail metric is the financed-sales one.)

**The decisive equity result — OPA's regressivity survives the convention most
favorable to it.** Median OPA value ÷ value, by price quintile:

| quintile | % cash | vs cash sale price | vs retail value |
|---|---|---|---|
| q1 (cheapest) | 61% | **1.543** | **1.347** |
| q2 | 35% | 1.080 | 1.024 |
| q3 | 19% | 0.935 | 0.919 |
| q4 | 13% | 0.912 | 0.907 |
| q5 (priciest) | 17% | 0.882 | 0.878 |

The retail convention (marking cash sales up to retail value — OPA's steelman)
**shrinks the cheap-tail over-assessment but does not remove it**: q1 goes from
1.543 to 1.347, still 35% above retail value while q5 sits at 0.88. The
regressive gradient is present under *both* conventions; the q1/q5 ratio is
1.75x against cash prices and still **1.53x against retail value**. So the
"cheap homes just sell for less" rebuttal is only partly true and cannot
rescue OPA: even valuing every cheap home at what a financed buyer would pay,
they are over-assessed relative to expensive homes. This is the robust,
pre-empted form of the regressivity finding. Artifacts:
`data/diagnostics/retail_vs_blend.parquet`.

## Fairness-robustness (`philly fairness-robustness`, 2026-07-04)

Three checks on the "demographic-free model eliminates the race gap" claim.
**(1) Mechanism** — a deliberately coarse model (hedonics + ward/ZIP dummies,
NO learned market areas / kNN surface / block rolls) closes the Black–White
level gap almost as well (−0.02) as the rich model (+0.01), while OPA sits at
+0.09. So the level correction is **sales-calibration, not rich spatial ML**;
richness buys uniformity (COD 17.6 vs 32.9), not the level fix. **(2) CV
folds** — the model's Black–White gap stays within ±0.03 across 5 temporal
folds (stable), while OPA's swings −0.10 (2020) → +0.09 (2025): OPA's gap is
time-varying and sign-changing (lag × differential appreciation), not a fixed
penalty. **(3) Full roll (sold+unsold)** — OPA vs model by race is mixed
(Hispanic 0.96 / 33% over 110%; Black 0.85, i.e. OPA *below* model), so the
sold-sales fairness result does NOT cleanly extend to the unsold stock (and
this compares OPA to our model, not ground truth). Net: the level gap is not
intrinsic to the data (any sales-calibrated model avoids it), but "we
eliminate the race gap" is overclaimed — the robust, convention-proof pieces
are vertical regressivity and the persistent ~2× dispersion gap. Report
Finding 3 rewritten to match.

## Robustness audit (`philly robustness-audit`, 2026-07-04)

Two adversarial stress tests. **(1) Char-leakage bound.** The model uses
today's characteristics for old sales; on the recent (2025–26) out-of-time
test, splitting by post-sale-permit status, the model's uniformity edge over
OPA is identical (8.2 COD points) on the leakage-safe 87% (no post-sale
permit, model ratio 0.971) and the leakage-exposed 13% — so the advantage is
not a hindsight artifact. **(2) Racial gap under the retail convention** —
the key finding, and two-sided:

| era | White | Black | Hispanic | Black−White |
|---|---|---|---|---|
| Controller (2016–19) vs sale price | 0.840 | 0.937 | 1.011 | +9.7 |
| Controller vs retail value | 0.824 | 0.867 | 0.927 | **+4.3** |
| Current (2023+) vs sale price | 0.886 | 0.937 | 0.942 | +5.1 |
| Current vs retail value | 0.878 | 0.891 | 0.881 | **+1.3** |

The historical racial gap **survives** the retail steelman (real bias, not
just cash composition); the current-era racial *level* gap is **largely
cash-composition-mediated** (minority tracts 36–59% cash vs 24% white),
shrinking to ~1 point — OPA has largely closed the direct level bias, and the
residual disparity now runs through the credit-access channel. Vertical
regressivity (cheap vs expensive) survives under retail in every era (q1/q5
1.53×). This nuance is reflected in
[report-assessment-equity.md](report-assessment-equity.md).

## Caveats

- Ecological, tract-level; ACS 2022 composition; the city layer's own
  majority-race classification.
- Ratio convention: assessment-for-sale-year vs later sale price (out-of-time);
  the Keene/IAAO TASP convention shifts levels, not group orderings.
- Sales-based ratio studies see only sold properties; unsold-stock bias applies
  to every study of this kind, including the Controller's.
- The condo-segment rows use each model run's out-of-time test window; condo
  ratios rest on recovered deed links (84% precision proxy, within-building
  near-misses).
