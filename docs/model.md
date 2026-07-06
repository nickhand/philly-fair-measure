# The Model: Architecture, Methodology, Results

A technical description of the Philadelphia residential AVM — the models, the
training discipline, and how it is evaluated against OPA. For *why* the design
choices are made (OPA's methodology, the 2026 AVM literature) see
[research-notes.md](research-notes.md); for the full input catalog see
[features.md](features.md); for the equity findings see
[report-assessment-equity.md](report-assessment-equity.md) and
[equity-diagnostics.md](equity-diagnostics.md).

## Purpose

An automated valuation model for Philadelphia residential property, built
entirely on public data, designed as an **independent, less-regressive
comparator to OPA's assessed values**. Three deliberate departures from OPA
practice shape the whole system:

1. **Independence.** No `asmt_*` field is a model input. A model that can see
   OPA's number would trivially copy it and the comparison would be circular;
   OPA's values enter only as the incumbent benchmark on the test set.
2. **Out-of-time evaluation.** Every reported metric is on a held-out *future*
   slice of sales, never a random split.
3. **Calibrated uncertainty.** Disagreements with OPA are gated by predictive
   intervals, so a flag reflects confidence rather than a bare point gap.

Demographic data (ACS) is used only in diagnostics and is **never** a valuation
feature.

## Scope and data

- **Universe:** ~465k residential parcels (`SINGLE FAMILY` + `MULTI FAMILY`);
  condominiums (OPA `88`-prefixed accounts) are modeled separately (§5.5).
  ~205k arm's-length sales form the training/evaluation base.
- **Sources:** OPA characteristics, DOR Realty Transfer Tax (sales + mortgage
  documents), L&I (permits/violations/complaints/investigations/licenses), PWD
  parcel geometry, SEPTA/PPR/streets for proximity, ACS (diagnostics only). See
  [source_inventory.md](source_inventory.md).
- **Target:** `log(sale_price)` in reference-month dollars via the district
  price index (§4), so the model predicts a time-neutral level and is moved to
  any date by the same additive adjustment.

## Split discipline

Out-of-time, per CCAO practice ([ccao-lessons.md](ccao-lessons.md)). Sales sort
by date; the most recent 10% is the **test set**, the most recent 10% of the
remainder is the **validation slice**. The validation slice does triple duty:
LightGBM early stopping, isotonic-calibration fitting (§5.2), and conformal
residual calibration (§5.6). The split is deterministic (sort by `sale_date`,
`sale_id`, then head/tail), so every artifact is reproducible from the mart plus
the persisted split fractions.

## 4. Feature set (92 features)

73 numeric + 19 categorical, no `asmt_*`. The full column-by-column registry is
[features.md](features.md); the families and their rationale:

| Family | Carries |
|---|---|
| Hedonic (`char_`) | area, beds/baths, year built, style, era, construction |
| Learned market areas (`loc_`) | k-means sale-price geography replacing OPA's hand-drawn zones |
| Constant-quality price index (`time_adj_log`) | BMN repeat-sales curves per district (ridge-shrunk to citywide) + shrunken per-market-area drift — a mix index overstated gentrifying-district appreciation by up to ±28% vs repeat-sale truth |
| As-of kNN surface (`mkt_knn_`) | distance-weighted mean of the *k* nearest **strictly earlier** sales — the between-block gradient trees can't interpolate; quarter-blocked against look-ahead |
| Rolling means (`mkt_*_roll_`) | block/building leave-one-out $/sqft level (the CCAO workhorse) |
| Parcel geometry (`shp_`) | area, perimeter, vertex/angle SDs, min-rotated-rect ratios from PWD polygons |
| Distress & tenure (`dist_`, `evt_`, `ten_`) | delinquency, severe violations, vacancy complaints, rental licenses (the q1 tail signal) |
| Mortgage forensics (`fin_`) | prior-mortgage count/recency, hard-money; `fin_cash_sale` is a *diagnostic* attribute, kept out of the model |
| Proximity (`prox_`) | rapid transit, rail, parks, expressway/arterial, bus density |

## 5. Models

### 5.1 LightGBM — primary point estimate
Gradient-boosted trees on the 92-feature encoding. `learning_rate=0.05`,
`num_leaves=255`, `min_data_in_leaf=40`, `feature_fraction=0.8`,
`bagging_fraction=0.8`, `lambda_l1=0.1`, `lambda_l2=1.0`, ≤5000 rounds with
100-round early stopping on the validation slice; categoricals passed natively.

### 5.2 Isotonic vertical calibration — the regressivity corrector
GBDTs compress toward segment means at the tails (over-valuing cheap homes,
under-valuing expensive ones — exactly PRD > 1). An isotonic regression of the
residual on the prediction, fit on the validation slice, removes that gradient
while remaining **monotone in the raw prediction** (it never reorders homes).
Serialized as knot coordinates to `vertical_calibration.json`.

The isotonic is fit on the **financed** validation slice (`calibrate_on_financed`,
default on), so predictions land on the *typical-financing market-value* standard
rather than the cash-blended sale level. Measured 2026-07-05: this moves the
financed-sample median ratio 0.95 → 1.00 with COD/PRD/PRB unchanged — a pure
centering gain that keeps the full training set (cash sales carry location signal;
see [research-notes.md](research-notes.md)). It falls back to the whole slice when
the financed subset is thin. Consequence: ratios against *cash* sale prices then
sit above 1.0 by design (cash homes transact below market value — the channel gap
the retail convention prices explicitly, §7). The §6 table predates this default.

### 5.3 Ridge — benchmark
A regularized linear pipeline (median-impute → standardize → one-hot) as a
transparent floor: if the GBDT can't beat a linear model, something is wrong.

### 5.4 Bayesian hierarchical model — uncertainty + the screen
A PyMC model sampled with nutpie (Rust NUTS) providing the posterior predictive
intervals the screen consumes:

- **Nested spatial intercepts** city → district → market-area, non-centered
  (`mu_city ~ N(12, 2)`, `tau_district ~ HalfNormal(0.5)`, `tau_area ~
  HalfNormal(0.3)`).
- **Hedonic effects** `beta ~ N(0, 1)` per standardized covariate.
- **Optional per-parcel latent quality**, identified by repeat sales,
  non-centered, with a zero slot absorbing singletons (off by default — adds
  ~nothing over the prior-price covariate; measured 2026-07-04).
- **Optional RBF spatial basis** (off by default — overlapping bumps are
  collinear, sample >15× slower, and the kNN covariate already carries the
  surface; measured 2026-07-03).
- **Heteroscedastic noise** `log σ = g₀ + z·g + district effect`, widening
  where evidence is thin (missing block roll, sparse kNN, atypical style).
- **Student-t likelihood** with fixed moderate ν (a learned ν couples every
  observation through one global parameter and samples for hours; fixed keeps
  the fat-tail robustness cheaply).

### 5.5 Condo model
Separate, per CCAO practice. Same discipline (out-of-time, time-adjusted,
isotonic-calibrated) with condo features: unit characteristics,
`unit_area_share` (the public-data stand-in for declared % ownership), and
building-level leave-one-out rolling means. `building_id` itself is not a
feature (~9k mostly-singleton levels would overfit); the rolling mean carries
the building signal, and the unit's own prior sale enters as the same
repeat-sales carry-forward the residential model uses (measured 2026-07-06:
repeat-segment COD 23.9 → 21.6, median ratio 1.063 → 1.035). The screen pairs
this LightGBM point estimate with conformal offsets (§5.6) — a
self-consistent anchor. The condo family also has a Bayesian arm (the §5.4
hierarchy on condo covariates with an evidence-only σ design), kept as a
research artifact rather than the screen's anchor: its median runs ~25% hot
out-of-time (the district price index over-adjusts condos) and, being
linear, it barely reacts to a unit's own prior sale.

### 5.5b New construction
A sale-comparison model prices a brand-new build against the older stock it
replaced and runs low (measured: new-build over-flag assessments at 3.2x our
medians, with active listings agreeing with OPA). Public-data response, all
from the deed data we already hold: a dedicated as-of kNN surface over sales
of *then-new* homes only (`mkt_newbuild_knn_*`, k=10, same leakage discipline
as §4's surface), an explicit `char_new_build` dummy plus the local
new-vs-old premium as features, and a `newbuild_thin` term in the Bayesian σ
design so a new build with <3 new-build comps nearby gets a wider, honest
interval. Measured on the 370 out-of-time new-build test sales: LightGBM
median ratio 0.90 → 0.98 (bias gone), Bayesian coverage 0.93 → 0.95 at width
1.81; citywide metrics unchanged. Screen policy on top: homes built within
two years of the valuation date never flag "over" (they demote to the
attention tier with a report caveat), and records with no recorded living
area get `insufficient_record` instead of a verdict.

### 5.6 Conformal intervals — frequentist cross-check
Split-conformal intervals around the LightGBM point model, sharing **nothing**
with the Bayesian arm except the feature mart — different model, different
uncertainty mechanism. Offsets are asymmetric (the cheap-tail residual
distribution is left-skewed), in global / Mondrian-by-district / kNN-locally-
weighted variants. Where **both** the Bayesian posterior and the conformal band
put OPA's value outside their 90% interval, the flag is robust to either
method's assumptions.

### 5.7 Conformalized quantile regression — bake-off and adoption
`fair-measure cqr-check` trains LightGBM quantile heads (q05/q95) on the fit
slice, conformalizes their miss on the validation slice (globally and with
the same spatially weighted kNN correction as 5.6), and compares every
interval system on the untouched out-of-time test slice. Measured 2026-07-06
(nominal 90%): cqr-knn covers 88.9% at median log-width **0.91** vs the
fixed-offset conformal-knn's 89.4% at 0.97 (≈6% narrower bands) and the
Bayesian posterior's 91.1% at 1.31; in the expensive quintiles cqr is much
sharper (q4/q5 width 0.65 vs 0.74/0.75 conformal) at 89–92% coverage, and its
by-district coverage floor is the best of the four (0.864 vs 0.856 conformal,
0.770 raw Bayesian). **No method fixes the cheap-tail undercoverage** (q1:
cqr 0.850, conformal 0.858, Bayesian 0.790 — vs 90 nominal); q1 misses are
genuine outliers, not a width-model failure. **Adopted for the residential
screen (Stage 3b):** every baseline/retail run persists q05/q95 quantile
heads (trained on the fit slice only — the validation slice stays clean as
the CQR calibration set), and the screen's second machine is the spatially
weighted CQR band around them. Measured effect on flags: over-candidates
429 → 222 — the feature-adaptive band widens exactly on the high-variance
homes that produce marginal over-calls, so the agreement gate vetoes them
into the watch tier — while under-candidates are ~unchanged (6,353 → 6,289).
Condos keep the 5.6 fixed-offset variant (their band is the flag anchor, not
a cross-check, and the bake-off was residential-only).

## 6. Results

Out-of-time test set, n≈19.5k, run `20260706T202658Z-baseline`. Identical test
set and treatment; OPA's own values as the incumbent:

| Model | RMSE(log) | MAPE | Median ratio | COD | PRD | PRB | MKI |
|---|---|---|---|---|---|---|---|
| **LightGBM** | **0.333** | **26.4%** | 1.031 | **25.5** | **1.087** | **−0.073** | 0.905 |
| Ridge | 0.427 | 37.4% | 1.045 | 35.5 | 1.061 | −0.080 | 0.981 |
| **OPA (incumbent)** | 0.449 | 34.0% | 0.983 | 34.5 | 1.190 | −0.234 | 0.787 |

The model is **more accurate** (RMSE 0.337 vs 0.449), **more uniform**
(COD 25.8 vs 34.5), and **markedly less regressive** (PRD 1.07 vs 1.19; PRB
−0.06 vs −0.23) than OPA on the same homes. The raw-sample median ratio runs
1.04 (the financed-calibrated booster sits above the cash-heavy raw test
slice); on the IAAO financed/TASP basis the median is 1.002 with COD 19.9
(see `fair-measure export-web-stats` / the site's ratio card). IAAO ratio
statistics (COD, PRD, PRB, MKI) come from assesspy; definitions in
[ccao-lessons.md](ccao-lessons.md).

Honest caveats:

- The full-sample **COD 25.9 is above the IAAO ≤15 target** — it includes the
  cash/distressed tail. On an IAAO-standard trimmed arm's-length sample the model
  clears the vertical-equity bands (COD 17.0, PRD 1.03, PRB −0.02) while OPA does
  not — see the [vertical-equity report card](vertical-equity-report-card.md).
- **Condos are the exception:** the condo LightGBM roughly *ties* OPA
  (RMSE 0.280 vs 0.278, COD 22.4 vs 18.8; 2026-07-04). Condos are homogeneous
  and sell frequently — where OPA's mass appraisal already does well.
- **Interval undercoverage in the cheap tail:** at nominal 90%, realized
  coverage is ~89–91% overall but only **~81–86% in the cheapest quintile**
  across every interval method built (Bayesian 0.81, fixed-offset conformal
  0.86, CQR 0.85 — see §5.7). Q1 dispersion is partly irreducible; the
  machines report the shortfall rather than hide it.

Stability is checked by temporal cross-validation (rolling out-of-time folds)
and spatial cross-validation (leave-one-district-out); see the `fair-measure
temporal-cv` / `spatial-cv` commands and [equity-diagnostics.md](equity-diagnostics.md).

## 7. Application: the assessment screen

Scoring the full roll yields, per parcel: a point value, a 90% predictive
interval, an `over_assessed_candidate` / `under_assessed_candidate` /
`within_range` flag driven by whether OPA's value falls outside that interval,
and `screen_z` — the disagreement expressed in predictive-uncertainty units
(log-ratio of OPA to the estimate, divided by the interval's log-width scaled
to one standard deviation). The interval method is chosen per family to be
self-consistent with the point estimate:

- **Houses** — the hierarchical Bayesian posterior predictive interval
  (`interval_method="bayesian_posterior"`), with the spatially weighted CQR
  band around the LightGBM quantile heads as the second machine: an
  over/under flag requires **both** to place OPA outside on the same side
  (measured 2026-07-06: the second machine disputed 30% of Bayesian-only
  flags, concentrated on gentrification-edge blocks where the two arms
  disagree about the price level; disputed rows demote to the attention
  tier). **Surfaces show one self-consistent pair** (`display_median` /
  `display_pi_*`): the calibrated LightGBM point — the machine the drivers
  and comps panels explain — with its own CQR band. Intersecting the two
  bands was measured and retired: two 90% bands intersected guarantee only
  80% (union bound), and the shipped intersection realized 86.0% overall /
  72.9% in q1 against its "90%" label, while the CQR band alone realizes
  89.1% at the narrowest valid width.
- **Condos** — split-conformal, kNN-locally-weighted offsets around the condo
  LightGBM prediction (`interval_method="conformal_knn"`), a single
  self-consistent machine. The Bayesian condo arm exists as a research
  artifact but does not drive flags: its district index over-adjusts
  homogeneous condo stock, and its linear form is too stiff to absorb
  unit-level evidence such as a prior sale of the same unit.

Guards keep the flags honest where the record, not the value, is the problem:

- **New construction** (year built within two years of the valuation year)
  never flags as over-assessed — the sale history the model learns from lags
  the finished building. Such homes demote to within-range, surface in the
  attention tier instead, and carry an explicit caveat on their report.
- **Insufficient records** (no recorded livable area) are reported as
  `insufficient_record` and are not valued at all rather than being priced as
  if the missing size were real.
- **Attention tier** ("worth a look"): properties inside the interval but in
  its outer part (|`screen_z`| > 1) are labeled high/low attention rather than
  flagged, so the strong flags stay reserved for cases outside the model's
  stated uncertainty.

As of run `20260706T222312Z` (Tax Year 2027 roll): 496,975 properties
screened — 1,643 over-assessed candidates, 6,253 under-assessed candidates,
44,408 in the attention tier, 93 insufficient records. (The constant-quality
index cut under-assessed candidates nearly in half: the retired mix index
inflated estimates in gentrifying districts, manufacturing spurious
under-flags.) A coherence gate
refuses to screen against feature marts and model runs from different
generations (`StaleRunError`) rather than silently mixing them, and every
build must pass the structural invariants in `validation/screen_audit.py`
(no flag the second machine disputes; no display band that excludes its own
median) plus a run-over-run audit (`fair-measure screen-audit`).

Two value conventions are surfaced explicitly:

- **Blend** — predicts the actual (cash-and-financed) market; matches realized
  sale prices.
- **Retail** — trained on financed sales only (the legal "typical-financing
  market value" standard); for cash-market homes it applies a **published
  per-quintile channel discount**, not a hidden propensity score, so an owner
  or a board can inspect the exact number. The bifurcation is quantified in
  [report-assessment-equity.md](report-assessment-equity.md).

## 8. What makes it defensible

Independence from OPA (no `asmt_*` inputs) · no demographic valuation features ·
strict out-of-time evaluation · uncertainty-gated flags requiring two
independent interval methods (Bayesian posterior and spatially weighted
conformal) to place OPA outside on the same side · published channel
discounts rather than opaque adjustments · deterministic, reproducible
pipeline · a full model-vs-OPA benchmark on every run.

## 9. Known limitations

Cash-market dispersion is partly irreducible; condos remain OPA's best
segment (we beat their rmse, trail their COD by ~0.5); interval
undercoverage in q1; OPA's interior-condition fields are stale and unavailable
to verify (the model routes around them via distress/permit signals); single
metro, no cross-city validation.
