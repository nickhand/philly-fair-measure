# Equity Diagnostics: Assessment Ratios by Tract Racial Composition

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
