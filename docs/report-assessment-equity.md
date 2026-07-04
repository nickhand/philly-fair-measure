# Regressive by Design, Not by Necessity: Racial and Economic Patterns in Philadelphia Property Assessments

**A public-data analysis — working draft, July 2026, pending external review.**

*Every figure in this report is reproducible from open City of Philadelphia
data with the accompanying open-source tool. Demographic data is used only to
audit outcomes — never to value property — mirroring the Office of Property
Assessment's (OPA) own legal constraint.*

---

## Executive summary

Philadelphia's property assessments are **regressive**: lower-value homes are
assessed at a higher fraction of their worth than higher-value homes, and the
pattern falls disproportionately on majority-Black and majority-Hispanic
neighborhoods. This is not a new claim — the City Controller documented it for
2014–2019. This analysis confirms it on independent data, tests it against the
strongest counter-arguments, and adds five findings that change what the city
should conclude from it:

1. **The regressivity is real and racially patterned.** In the Controller era,
   the least-white quartile of tracts was assessed *above* market value at the
   median (1.10) while the whitest quartile sat 16% *below* (0.84) — with
   uniformity more than twice as poor (COD 61 vs 27).

2. **Recent reassessments substantially closed the direct racial gap — but not
   the deeper one.** The extreme-quartile gap fell from ~26 to ~9 ratio points,
   and once cash-market composition is accounted for, the *current-era* racial
   level gap nearly disappears (OPA largely fixed it). The historical
   (2014–2019) racial gap, by contrast, survives that adjustment — it was real.
   And the **vertical** regressivity (cheap over-assessed relative to
   expensive) survives every adjustment in every era.

3. **The level gap is not intrinsic to the data.** A model built *only* from
   public data with *no* demographic information does not reproduce OPA's
   White/Black median-ratio level gap (which reaches ~9 points) — and neither
   does a deliberately simple hedonic model, so the fix is sales-calibration,
   not sophistication. This holds across a 5-fold temporal cross-validation.
   Two honest limits: OPA's gap is itself time-varying (it has flipped sign
   since 2020), and the persistent, convention-proof racial disparity is
   **dispersion** (minority tracts ~2× the scatter), which no model here
   eliminates.

4. **There is no accuracy excuse.** Adding the exact income/race/poverty data
   OPA is legally barred from using improves accuracy by essentially nothing
   (1.15% of model signal; overall error unchanged). Fairness and the legal ban
   on people-data are not in tension.

5. **The "cheap homes just sell for less" rebuttal fails — but the truth is
   subtler.** About 40% of Philadelphia's arms-length sales are cash, at a
   deep discount that survives every control. Even valuing every home at what a
   *mortgage-financed* buyer would pay — the standard most favorable to OPA —
   cheap homes are still assessed ~1.5× higher, relative to value, than
   expensive homes, and this holds in **every** period from 2016 to 2025 under
   both conventions (the one finding that is convention-proof, era-proof, and
   cross-validated). The residual regressivity is a **bifurcated-market and
   assessment-standard problem**, not merely an assessor error.

The through-line: Philadelphia can assess fairly with the data it already has.
Where it does not, the burden falls hardest on the neighborhoods least able to
absorb it.

---

## Background

Property taxes fund a large share of Philadelphia's schools and services, and
each owner's bill is proportional to OPA's estimate of their home's market
value. Two properties of a fair assessment system:

- **Uniformity** — comparable properties should be assessed comparably.
  Pennsylvania's constitution contains a *Uniformity Clause*, and uniformity is
  a recognized basis for tax appeal. The standard industry measure is the
  **Coefficient of Dispersion (COD)** — the average percent deviation of
  assessment-to-sale ratios from their median. The IAAO considers COD ≤ 15
  acceptable for older/heterogeneous residential stock.
- **Vertical equity** — the assessment-to-value *ratio* should not depend on
  value. When cheap homes are assessed at a higher ratio than expensive ones,
  the system is **regressive**, and low-value owners over-pay relative to
  high-value owners. The standard measures are the **Price-Related Differential
  (PRD)** (>1.03 indicates regressivity) and the median ratio by price tier.

The City Controller's *Property Assessment Review* found OPA's 2014–2019 rolls
regressive and least uniform in lower-income West, North, and Southwest
Philadelphia. This report re-tests those findings on independent data and asks
the questions a rigorous critic would: *Is it racial or just economic? Is it
fixable? Would better data help? Are cheap homes simply worth less?*

---

## Data and method

- **Sales.** 202,587 validated, arms-length residential sales, drawn from the
  city's Real Estate Transfer (deed) records and classified with a
  transparent, industry-standard sales-validation pipeline (nominal, distressed,
  multi-parcel, and duplicate transfers excluded). Condominiums are analyzed
  separately.
- **Assessments.** OPA's published market values, matched to each sale by the
  assessment year in effect.
- **Demographics — audit only.** Tract racial composition and majority-race
  classification come from the city-published American Community Survey (ACS)
  2022 tract layer, joined spatially to 2020 census tracts. **These variables
  never enter any valuation model** — they are used solely to measure outcomes,
  exactly as OPA is itself legally required to do. Tract-level analysis is
  *ecological*: it describes places, not individual owners.
- **The comparison model.** An independent valuation model (gradient-boosted
  trees plus a Bayesian hierarchical model for uncertainty) trained only on
  public data — property characteristics, validated prior sales, permits, and
  learned neighborhood price surfaces. It contains no income, race, or crime
  data.
- **Convention.** Ratios are OPA value for the sale year ÷ the later sale price
  (an out-of-time test). Levels shift under other conventions; between-group
  *gaps*, which are the subject here, are robust to the choice. All figures are
  reproducible via the open-source `philly` command-line tool named in the
  Appendix.

---

## Findings

### 1. Assessments are regressive, and the pattern tracks race

**Controller era (2016–2019 sales, n = 83,240):**

| Group | median ratio | COD | PRD |
|---|---|---|---|
| Majority-White tracts | **0.840** | 29.2 | 1.152 |
| Majority-Black tracts | **0.937** | **63.1** | **1.479** |
| Majority-Hispanic tracts | **1.011** | 53.8 | 1.323 |
| Least-white quartile (0–7% white) | **1.099** | 60.6 | 1.383 |
| Whitest quartile (61–100% white) | **0.836** | 27.1 | 1.141 |

The least-white quartile was assessed *above* market value at the median while
the whitest sat 16% below — a 26-point monotonic gradient — with dispersion
more than twice as high and far stronger within-group regressivity. This
confirms the Controller's conclusions on both the economic and racial framings.

### 2. Reassessments narrowed the gap but did not close it

**Current era (2023+ sales vs post-TY2023 rolls, n = 54,400):**

| Group | median ratio | COD | PRD |
|---|---|---|---|
| Majority-White tracts | 0.886 | 23.5 | 1.084 |
| Majority-Black tracts | 0.937 | 45.9 | 1.228 |
| Majority-Hispanic tracts | 0.942 | 47.4 | 1.270 |

The extreme-quartile gap fell from ~26 to ~9 ratio points — consistent with
OPA's claimed year-over-year improvement. Majority-Black and Hispanic tracts
remain assessed ~5 points higher relative to *actual sale prices*, at roughly
double the dispersion (COD ~46 vs ~24) — but, as the robustness section below
shows, most of that residual *level* gap is now cash-market composition rather
than direct assessment bias. The persistent, convention-proof problem in the
current era is **dispersion** (uniformity), not the racial level gap OPA has
largely closed. Progress that is real, and incomplete in a specific way.

### 3. The gap is not inevitable — a demographic-free model nearly eliminates it

On identical out-of-time test sales (n = 19,464):

| Group | OPA median | Model median | OPA COD | Model COD |
|---|---|---|---|---|
| Majority-White tracts | 0.948 | 0.992 | 20.6 | 17.6 |
| Majority-Black tracts | 1.035 | 0.988 | 42.7 | 32.9 |
| Majority-Hispanic tracts | 1.021 | 0.954 | 43.9 | 32.9 |

OPA's **8.7-point** White/Black median-ratio gap collapses to **0.4 points**
under the public-data model, which contains no demographic features — while
uniformity improves in every group. But this single-window number needs three
robustness checks before it can carry weight, and they qualify it in
important ways (`philly fairness-robustness`):

- **It is stable across time — the strong result.** Re-run per fold in a
  5-fold temporal cross-validation, the *model's* Black–White level gap stays
  within ±0.03 in every period (−0.026 to +0.015), while *OPA's* swings from
  −0.10 (2020) to +0.09 (2025). So the model consistently does not reproduce a
  racial level bias, whatever OPA's is in a given roll — but note OPA's gap is
  itself **time-varying and sign-changing**, entangled with assessment lag and
  differential neighborhood appreciation, not a fixed "race penalty."
- **The mechanism is sales-calibration, not sophisticated modeling.** A
  deliberately *coarse* model (basic hedonics + ward/ZIP dummies, none of our
  learned market areas or nearest-sales price surface) *also* closes the level
  gap (Black–White −0.02 vs OPA's +0.09). So the gap is not a hard problem
  requiring rich spatial ML — *any* model calibrated to recent sales avoids it.
  Richness buys **uniformity** (COD 17.6 vs 32.9), not the level correction.
  The honest implication cuts toward OPA: you do not need fancy tools to be
  fairer than the current roll on level bias.
- **The full-roll (sold + unsold) evidence is mixed** — the appropriate
  humility. Comparing OPA to the model across all 464k residential properties,
  Hispanic tracts show more over-assessment (median OPA/model 0.96, 33% above
  110%) but Black tracts show OPA *below* the model (0.85), the opposite of the
  sold-sales story. This measurement compares OPA to *our model* rather than to
  ground-truth sales, so it inherits the model's errors on never-sold homes; it
  should be read as "the sold-sales fairness result does not cleanly extend to
  the unsold stock," not as a second confirmation.

So the defensible claim is narrower than "we eliminate the race gap": *the
systematic level bias OPA exhibits in a given roll is not intrinsic to the data
— any sales-calibrated model avoids it — but OPA's gap is time-varying, the
fix is not exotic, and the full-roll picture is unresolved.* What is
unambiguous and convention-proof is the **vertical** regressivity (Finding 5)
and the persistent **dispersion** gap (minority-tract COD ~2× under both OPA
and the model — low-value, thin-market homes are genuinely harder to value for
anyone, and this we do *not* eliminate).

### 4. There is no accuracy excuse: the banned data would not help

A natural objection is that OPA is *forced* to be less accurate in poor
neighborhoods because it cannot use income or demographic data. We tested this
directly by retraining the model *with* the ACS income/race/poverty variables
added — the exact data the law forbids.

The result: those features carry **1.15%** of the model's total signal, overall
error is unchanged (COD 26.286 → 26.284, a hair *worse* on some measures), and
no racial group's ratio or dispersion moves beyond noise. The model's learned
neighborhood price surfaces already capture everything tract demographics could
proxy. **The legal ban on people-data costs essentially nothing.** Accuracy and
legal fairness are not in tension — which removes the last excuse for
demographic-correlated assessment error.

### 5. "Cheap homes just sell for less" — the rebuttal, tested and answered

The sharpest defense of OPA is that low-value homes genuinely transact below
their "true" value, inflating the ratio. There is real substance to this, and
it deserves a real answer.

**About 40% of Philadelphia's arms-length sales are cash**, and cash sales
transact far below mortgage-financed sales of comparable homes. This is a
credit-access phenomenon: below roughly $70–100k, mortgages are effectively
unavailable (origination costs make small loans uneconomic), many low-value
homes cannot pass a financing appraisal, and tangled title blocks conventional
sale — so the only buyers are cash investors, who price to a return, not to
shelter value. The cash market dominates precisely the cheap tail.

We measured the pure size of this channel discount by controlling, step by
step, for everything observable:

- Raw within-neighborhood cash discount: **−43.6%**
- After controlling for house composition (size, beds, condition, style): −30.0%
- After adding the full distress stack (delinquency, vacancy, unpermitted work,
  code violations): **−29.4%** (95% CI −29.7 to −29.1)

Distress explains almost none of it; the discount is a genuine market channel,
largest in the cheapest tier (−21.6%) and near zero at the top (−2.7%).

This means part of the raw ratio *is* market bifurcation — but it does **not**
rescue OPA. We built a **retail-value** estimate (trained only on
mortgage-financed sales, the typical-financing standard the law targets) and
re-ran the ratio study against it:

| Price quintile | % cash | OPA vs cash sale price | OPA vs retail value |
|---|---|---|---|
| Cheapest (q1) | 61% | **1.543** | **1.347** |
| q2 | 35% | 1.080 | 1.024 |
| q3 | 19% | 0.935 | 0.919 |
| q4 | 13% | 0.912 | 0.907 |
| Priciest (q5) | 17% | 0.882 | 0.878 |

Even measured against retail value — marking every cheap home up to what a
*financed* buyer would pay, the interpretation most favorable to OPA — cheap
homes remain assessed **1.53× higher relative to value** than expensive homes
(1.75× against actual sale prices). The regressive gradient survives the
steelman.

And the finding relocates the deeper harm: a low-income owner in a
credit-starved neighborhood is taxed on a *retail value they cannot realize*,
because the only buyers for their block are cash investors. Taxing a value the
owner is structurally locked out of is its own regressivity — and it raises a
policy question OPA cannot answer alone: **is "typical-financing market value"
the right tax basis in a market that has no typical financing?**

### 6. This is not gaming — it is structural

We checked whether the pattern reflects "sales chasing" (selectively
reappraising sold properties toward their sale price, which would flatter the
statistics). It does not: the same roll's ratio dispersion on sales OPA could
have seen before certification differs by under two COD points from sales it
could not have seen, and standard sales-chasing detectors are negative. The
regressivity is a property of the model and the market, not of manipulation —
which is why it is fixable by better modeling.

### 7. The mirror image: the best-assessed segment is the affluent one

Condominiums — an affluent-skewing, heavily Center City stock — are OPA's
**best-assessed** segment (median ratio 0.91, COD 18.8) — more accurate, more
uniform, and slightly *under* market. Cheap rowhomes, disproportionately in
majority-Black and majority-Hispanic tracts, get the dispersed, regressive
treatment. The problem is not that OPA *cannot* assess accurately; it is that
its accuracy is distributed along lines that track wealth and race.

---

## Robustness: two stress tests a critic would demand

We ran the two measurements a hostile reviewer would push on hardest, because
"we acknowledged it" is a weaker answer than "we measured it."

**Stress test 1 — does the comparison model cheat with post-sale
characteristics?** The model uses *today's* property characteristics for every
sale, so a home renovated between its sale and now could leak future
information and inflate the model's apparent edge over OPA (which valued
blind). Two facts bound this. First, the out-of-time test is recent (2025–2026
sales), so little time has elapsed for renovation. Second, splitting the test
by whether *any permit was issued after the sale* — the proxy for "the property
changed" — the model's uniformity advantage over OPA is **identical on both
sides**:

| test subset | share | model COD | OPA COD | model's edge |
|---|---|---|---|---|
| No post-sale permit (leakage-safe) | 87% | 25.0 | 33.2 | **8.2** |
| Post-sale permit (leakage-exposed) | 13% | 28.1 | 36.2 | **8.2** |

If leakage drove the model's advantage, the edge would balloon on the
renovated subset. It does not — the model beats OPA by the same 8.2 COD points
where the property demonstrably did *not* change, with a near-unbiased ratio
(0.971). The model's advantage is real, not an artifact of hindsight.

**Stress test 2 — is the racial gap just cash-sale composition?** The rebuttal:
minority tracts have more cash sales, so lower prices, so higher OPA ratios —
adjust for that and the racial gap vanishes. We re-ran the tract-race study
against **retail-equivalent** prices (cash sales marked up by the measured
channel discount). The result is genuinely two-sided and worth stating plainly:

| | White | Black | Hispanic | Black−White gap |
|---|---|---|---|---|
| **Controller era (2016–19), vs sale price** | 0.840 | 0.937 | 1.011 | +9.7 pts |
| **Controller era, vs retail value** | 0.824 | 0.867 | 0.927 | **+4.3 pts** |
| **Current era (2023+), vs sale price** | 0.886 | 0.937 | 0.942 | +5.1 pts |
| **Current era, vs retail value** | 0.878 | 0.891 | 0.881 | **+1.3 pts** |

Two honest conclusions:

- **The historical (Controller-era) racial gap is robust** — it survives the
  retail convention (Black +4.3, Hispanic +10.3 points over White). The
  2014–2019 disparity was *not* merely cash composition; it was real assessment
  bias on top of the bifurcated market. The Controller's finding stands.
- **The current-era racial *level* gap is now largely cash-composition-
  mediated** — it shrinks to ~1 point under the retail convention. This means
  OPA's post-TY2023 reassessments have substantially closed the *direct* racial
  level bias, and the residual racial disparity now operates through the
  **credit-access channel**: minority tracts are cash-dominated (36–59% vs 24%
  for white tracts), so their owners are taxed toward a retail value the thin
  local market cannot deliver. Same harm, more precisely located — and it
  points at the structural root (mortgage access), not at an assessor's thumb.

Crucially, the **vertical** regressivity — cheap homes over-assessed relative
to expensive ones — is the finding that does not move, and we verified it the
same way we verified everything else: across five consecutive time periods
(2016→2025) *and* both value conventions. In **every** period the cheapest
quintile is assessed at a higher fraction of value than the priciest (q1/q5
ratio vs retail value: mean 1.53, minimum 1.21 — never below regressive), and
the canonical IAAO Price-Related Differential exceeds its 1.03 regressivity
threshold in every period under both conventions (PRD vs retail: mean 1.152,
minimum 1.075). It was worst in 2016 (q1/q5 = 1.9 vs retail), reached a low
around 2019–2021, and has **rebounded** in the post-TY2023 rolls (back to
1.6) — the same reassessments that closed the racial *level* gap did not fix,
and recently worsened, the vertical regressivity. This is the anchor of the
analysis: convention-proof, era-proof, and measured as a distribution, not a
single split.

Three conclusions follow from the evidence, in increasing order of ambition:

1. **The regressivity is fixable with data OPA already has.** A public-data
   model with no demographic inputs nearly eliminates the racial level gap and
   improves uniformity everywhere. Modern spatial modeling — learned
   neighborhood price surfaces rather than administrative geographies — is the
   proximate fix, and it is well within the reach of a modern assessment office
   (Cook County, IL runs exactly such an open-source system).

2. **Transparency should be routine.** OPA should publish ratio studies broken
   out by tract income and racial composition every cycle, and open its
   methodology and (de-identified) model, as peer jurisdictions do. An outside
   analyst reproduced these findings from public data in weeks; the office can
   monitor them continuously.

3. **The market-value standard itself needs examination in bifurcated
   markets.** The deepest finding is that "market value" is ambiguous where
   there is no functioning retail market — and the ambiguity falls on
   low-income owners. Remedies span assessment policy (how to define the basis,
   or targeted relief such as expanded LOOP/homestead protections tied to the
   realizable-value gap) and the structural root: **credit access** — the
   small-dollar-mortgage and tangled-title crises that force the cash market in
   the first place. The last is beyond OPA's remit, but it is the mechanism, and
   naming it correctly is a precondition for any durable fix.

---

## Limitations

This analysis is honest about what it cannot claim:

- **Ecological.** Tract-level race/income describes *places*, not the
  individuals who own or pay. Group gaps are robust; no individual owner's
  circumstance is inferred.
- **Observational.** The channel-discount and value estimates control for rich
  observables but are not experiments; unobserved condition (interior state) is
  not visible in public data and cannot be fully separated from the channel
  effect. This is a limit shared by OPA's own process, which does not inspect
  interiors.
- **Sold-stock bias.** Ratio studies see only properties that sold. This applies
  equally to this analysis and the Controller's, and to OPA's own studies.
- **The comparison model is a demonstration, not a replacement.** It shows the
  gap is *closable* with public data; it is not offered as OPA's production
  model, and it inherits the roll's own characteristic errors.
- **Convention-dependence, disclosed.** Where the choice of value convention
  (cash vs retail) materially changes a number, both are reported. That
  transparency is the point: which convention is *fair* in a bifurcated market
  is a genuine policy question, not a technical one to be hidden.

---

## Appendix: reproducibility

Every figure above is regenerated from public data by the open-source `philly`
tool:

| Finding | Command |
|---|---|
| Ratio study by tract race/income (F1, F2, F3, F7) | equity diagnostics (`docs/equity-diagnostics.md`) |
| Banned-data sensitivity (F4) | `philly acs-sensitivity` |
| Cash/financed channel decomposition (F5) | `philly channel-decomp` |
| Retail vs cash convention (F5) | `philly retail-market` |
| Char-leakage bound + racial gap under retail (Robustness) | `philly robustness-audit` |
| Fairness robustness: mechanism, CV folds, full roll (F3) | `philly fairness-robustness` |
| Vertical regressivity across periods + conventions (Robustness) | `philly regressivity-cv` |
| Temporal + spatial CV, look-ahead bound | `philly stability-audit` |
| Sales-chasing and convention bridge (F6) | `philly ratio-study` |
| Per-property both-value report | `philly report <address>` |

Data sources: OPA property assessments and characteristics, Real Estate
Transfer records, L&I permits/violations/complaints, PWD parcels, and the city
ACS tract layer — all public. The sales-validation, feature-engineering, and
modeling code is open for inspection and independent verification.
