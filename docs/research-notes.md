# Research Notes: OPA Methodology + State of the Art (2026)

Compiled 2026-07-02 from (a) OPA's *Mass Appraisal Valuation Methodology
Overview, Tax Year 2027* (released June 2026), and (b) an arXiv/literature
sweep on automated valuation, spatial ML, assessment equity, and uncertainty
quantification. Feeds [feature-plan-v2.md](feature-plan-v2.md).

---

## Part 1 — How OPA actually values property (TY2027 methodology digest)

Facts extracted from the official methodology document; page references to the PDF.

**Scope and timing**
- 580k+ properties; single-family = 73% (423,739 as of 2026-03-31). Effective
  date Jan 1, 2027 (p.1).
- **Sales window: 2020-01-01 → 2025-06-30** (p.3). Assessments certified before
  the tax year — OPA states plainly that values "may lag current market
  conditions." Our out-of-time evaluation quantifies that lag; their ratio
  study does not (see "reconciling metrics" below).

**Model form (pp.4–14)**
- Multiple Regression Analysis per market segment, **log-log multiplicative**:
  `Value = exp(constant) × Π adj_i^{0/1} × Π scalar_j^{coef_j}` — a hedonic in
  logs with backward elimination ("removing the least significant variables one
  at a time").
- Geography: **17 zones** (separate models) × **600+ Geographic Market Areas
  (GMAs)** as categorical adjustments, re-drawn annually from use/price/sales
  patterns. GMAs are published only as PDF maps — **verified not available as
  data** on the city ArcGIS org or CARTO (probed 2026-07-02).
- The sample calculation (p.14) reveals a **`SPATIAL` scalar covariate**
  (value ≈ 10394, exponent 0.162) — an interpolated location-value surface.
  OPA itself uses a smooth spatial price surface *on top of* GMA dummies.
- **Time adjustment**: a "compound adjustment index" per model calibrates every
  sale to the effective date; time variables are then *removed* from the final
  model (p.11). I.e., they model time-adjusted prices — the design we should
  copy (our models currently carry time features and visibly mis-extrapolate:
  LightGBM median ratio 0.92, Bayesian 1.12 on the most recent test year).
- **Land split is fiat**: residential land value = 20% of total (p.12), not
  modeled.

**Variables (p.10)**: property style, building SF, era built (banded age), lot
size, garage type/spaces, off-street parking *where valuable (Center City)*,
interior condition **or presumed interior condition** (inferred from permits,
aerial/street imagery, private listings — curb-only inspections), central air,
view amenity, proximity to amenities, street classification.

**Legally prohibited variables (pp.10–11)**: income (of anyone or any area),
ethnicity, crime statistics, length of ownership, owner identity, any
demographic data. "It is illegal for OPA to make any adjustment to value based
on data about people." → Our valuation model should stay comparable: ACS
socioeconomic features belong in *diagnostics*, not the valuation path
(sharpens the decision already recorded in features.md).

**Their reported performance (pp.15–16, external Keene ratio study, June 2026)**
- Against **time-adjusted sale prices (TASP)** on their validated in-window
  sample: overall median ratio 0.992, **COD 10.1**, PRD 1.016; by style:
  singles COD 6.7, twins 8.1, rows 10.7. Target median ratio band 0.95–1.02.
- STEB Common Level Ratio 94.3% (2025).

**Reconciling their COD 10.1 with our measured COD 34.6 for OPA — now fully
QUANTIFIED (2026-07-03, `philly ratio-study`).** Both numbers are real, on
different questions, and the bridge decomposes the gap on identical
out-of-time test sales (n=19,515):

| step (cumulative) | OPA COD | our model COD |
|---|---|---|
| out-of-time, raw (our headline) | 34.5 | 26.2 |
| + time-adjusted prices (TASP) | 32.8 | 26.2 |
| + fresh roll / in-window refit¹ | 31.3 | 20.1 |
| + IAAO 3×IQR ratio trim | 24.3 | 17.8 |
| + clean-sale curation² | **16.8** | **16.8³ / PRD 1.005** |

¹ OPA's row switches to the freshly reassessed TY2027 roll (the roll Keene
actually studied — the per-sale-year rolls are partly stale carry-forwards);
our row refits with the window inside training, the assessor-equivalent.
² Documented filters only, no ratio peeking: no legal-entity buyer/seller
(alone worth ~7 COD points — 43% of Philly arms-length sales involve an
entity), no possible-related parties, price ≥ $50k, single family. n≈9.6k.
³ Our 16.8 is the HONEST OUT-OF-TIME model on that sample (in-window would be
several points lower); PRD 1.005 and PRB 0.036 are dead inside the IAAO
bands (0.98–1.03 / ±0.05). By style, curated + trimmed: ours detached 13.7 /
twin 13.2 / row 17.9 vs Keene's reported 6.7 / 8.1 / 10.7.

The residual 16.8 → 10.1 for OPA is the layer we cannot reproduce from public
data: evaluator hand-review of the sale sample (IAAO-sanctioned but
discretionary — and the layer where validation that glances at the existing
assessment mechanically shrinks COD), their own tighter validation pipeline
(SVQs, deed review), time adjustment to their Jan-2026 valuation date rather
than our latest index month, and window choices. **Sale-chasing is ruled
out**: the same roll's trimmed TASP COD on sales OPA *could* see vs sales
recorded only *after* certification differs by <2 points (26.0/27.9 for
TY2025; 26.6/27.9 for TY2026), the %-within-2%-of-price is low and similar
in both windows, and assesspy's distribution heuristics are negative — an
exonerating finding worth stating plainly. Conclusion: the road from our
numbers to theirs is convention + curation, not model quality; on equal
footing our out-of-time model matches their in-window roll and beats it on
vertical equity (PRD/PRB), and the only honest lever for further out-of-time
COD is information the public data lacks (interior condition — the measured
q1 limit).

---

## Part 2 — State of the art for city-scale AVMs (2026 literature sweep)

**Tree ensembles remain the tabular accuracy standard; the frontier is what
you add to them.**
- Multimodal survey ([arXiv:2503.22119](https://arxiv.org/abs/2503.22119)):
  XGBoost/LightGBM/RF dominate tabular appraisal; imagery/text are active
  add-ons (later-stage for us per AGENTS.md).
- Interpretable mass cadastral valuation
  ([arXiv:2506.15723](https://arxiv.org/abs/2506.15723)): interpretability as a
  first-class constraint in official valuation, echoing IAAO practice.

**Accuracy and fairness are complements, not a tradeoff, when improvement
comes from features.**
- *Tradeoffs are Domain Dependent: Improving Accuracy and Fairness in Property
  Tax Assessments* ([arXiv:2605.15020](https://arxiv.org/abs/2605.15020); 26M
  sales, ~95% of U.S. counties): adding property features improves accuracy in
  most cases, and **when accuracy improves, fairness (vertical equity) almost
  always improves too**; census context helps both. Regressivity is largely a
  data/model deficiency — consistent with what our screen found in Philly
  (OPA q1 median ratio 1.54 on 2016–2026 sales).
- *Achieving Fairness and Accuracy in Regressive Property Taxation*
  ([arXiv:2312.05996](https://arxiv.org/abs/2312.05996)) and the IAAO vertical
  equity review (JPTAA vol 20): report a *suite* of vertical-equity tests
  (PRD is flawed alone) — we already compute PRD+PRB+MKI-capable metrics by
  quantile; keep quantile breakouts primary.

**Spatial structure: hybrid smooth-surface + discrete-area models.**
- *Gaussian Process Boosting*
  ([arXiv:2004.02653](https://arxiv.org/abs/2004.02653), GPBoost): tree
  boosting for the mean + GP/grouped random effects for space; fixes boosted
  trees' inability to interpolate smoothly in space (and their high-cardinality
  area problem); validated on housing data; scales via Vecchia approximations.
- Two-stage cluster analysis for location-specific drivers
  ([arXiv:2508.03156](https://arxiv.org/abs/2508.03156)): learn market areas
  from data, then model within/across them — exactly the GMA-analog we need
  since OPA's GMAs aren't published.
- Geo-spatial network embeddings / GNNs
  ([arXiv:2009.00254](https://arxiv.org/abs/2009.00254)): neighborhood graph
  context helps; our k-NN sale features are the simple version.
- Tract-level house price indexes via spatial dynamic factors
  ([JREFE 2023](https://link.springer.com/article/10.1007/s11146-023-09957-w))
  and granular repeat-sales indexes with spatial pooling
  ([arXiv:2512.01139](https://arxiv.org/abs/2512.01139)): fine-geography time
  indexes are feasible with pooling — supports a Philly zone/district-level
  monthly index for time adjustment.

**Uncertainty: calibration must hold *conditionally*, not just on average.**
- *Spatially weighted conformal prediction for AVMs*
  ([arXiv:2312.06531](https://arxiv.org/abs/2312.06531)): marginal conformal
  intervals are miscalibrated region-by-region; spatial weighting of
  non-conformity scores fixes local coverage. Two implications for us:
  (1) evaluate our Bayesian 90% coverage **by geography and price quintile**,
  not just overall (91.3% marginal can hide local failure); (2) a spatially
  weighted conformal wrapper around LightGBM is a cheap, strong frequentist
  complement to the Bayesian intervals.

**Spatial-field verdict for this project (measured 2026-07-03).** After the
kNN sale surface and learned market areas, out-of-time test residuals show
Moran's I = 0.051 (k=10 neighbors) and a noise-level distance correlogram —
essentially no latent field left to model. A GP field is therefore *not*
currently warranted; the earlier RBF-basis slowdown measurement indicted that
parameterization (overlapping collinear columns), not the HSGP idea, whose
orthonormal basis is well-conditioned. If richer models ever leave a residual
field, the 2026 toolchain: `pm.gp.HSGP` (PyMC, mature), GPBoost
(boosting + Vecchia GP, Python/R), and the newly released
[PyINLA](https://arxiv.org/abs/2603.27276) bringing R-INLA's SPDE machinery
to Python.

**Conformal cross-check verdict (measured 2026-07-03,
`philly conformal-check`, artifacts in the baseline run dir).** The
spatially weighted conformal wrapper proposed above is now built
(models/conformal.py: split-conformal on the rebuilt validation slice,
asymmetric residual quantiles, global / district-Mondrian / kNN-weighted
variants) and the cross-check **passes**: on the same 19,516-sale out-of-time
test, conformal-kNN covers 89.8% at median log-width 0.98 vs the Bayesian
90.1% at 1.30 — same coverage, ~25% narrower, because it wraps the stronger
LightGBM point model while the linear Bayesian pays in width. Exactly as
arXiv:2312.06531 predicts, marginal (global) conformal hides local failure —
district coverage spans 0.798–0.998 — while the spatially weighted variant
tightens the spread to 0.875–0.916, the best of all methods including the
Bayesian (0.858–0.926). Flag agreement on the full screen: the independent
machine confirms 76% of Bayesian under-assessment flags (1,710/2,411) and 40%
of over-flags (174/434); its narrower bands also flag ~19k borderliners the
Bayesian screen calls within-range. Screen policy unchanged — Bayesian stays
primary for residential (more conservative, posterior-draw semantics), the
double-flagged intersection (~1.9k properties) is the highest-confidence
actionable set, and the conformal engine prices the condo screen, which has
no Bayesian arm. All methods still undercover q1 (0.78–0.85 vs 0.90) — the
measured interior-condition information limit; kNN-conformal degrades most
gracefully (0.852 at width 1.42).

**Modern Bayesian practice applicable here**
- **HSGP** (Hilbert-space GP approximation; Solin & Särkkä, and the practical
  probabilistic-programming variant) gives near-exact low-dimensional GPs at
  O(n·m) — a smooth spatial surface over (lon, lat) with ~200–400 basis
  functions is tractable for 176k rows in PyMC (`pm.gp.HSGP`). This is the
  principled version of OPA's `SPATIAL` covariate.
- **Robust likelihood**: Student-t observation model for heavy-tailed sale
  prices — our Normal σ≈0.45 is inflated by tails, which is why intervals are
  honest but wide (mean width 1.60× the point estimate). Expect narrower
  intervals at equal coverage.
- **Time as a random walk / spline over months** (partial pooling across time)
  instead of a linear trend — the linear trend caused the 1.12 overshoot.
  Or adopt OPA's design: time-adjust prices first, model second.
- **Heteroscedastic σ** by property tier/evidence density (Case–Shiller models
  error variance explicitly; our `block_roll_missing` coefficient already
  shows evidence-density effects) — improves interval sharpness where data are
  dense and honesty where sparse.
- **Calibration diagnostics**: PIT histograms + coverage by segment;
  PSIS-LOO (arviz) for model comparison.

## Sources

- OPA, *Mass Appraisal Valuation Methodology Overview, TY2027* (June 2026) — user-provided PDF
- [arXiv:2605.15020 — Tradeoffs are Domain Dependent: Improving Accuracy and Fairness in Property Tax Assessments](https://arxiv.org/abs/2605.15020)
- [arXiv:2312.06531 — Uncertainty quantification in AVMs with spatially weighted conformal prediction](https://arxiv.org/abs/2312.06531)
- [arXiv:2004.02653 — Gaussian Process Boosting](https://arxiv.org/abs/2004.02653)
- [arXiv:2312.05996 — Achieving Fairness and Accuracy in Regressive Property Taxation](https://arxiv.org/abs/2312.05996)
- [arXiv:2503.22119 — Multimodal ML for Real Estate Appraisal: Survey](https://arxiv.org/abs/2503.22119)
- [arXiv:2506.15723 — Interpretable models for mass cadastral valuation](https://arxiv.org/abs/2506.15723)
- [arXiv:2508.03156 — Two-stage cluster analysis for location-specific price drivers](https://arxiv.org/abs/2508.03156)
- [arXiv:2009.00254 — Geo-Spatial Network Embedding for house prices](https://arxiv.org/abs/2009.00254)
- [arXiv:2512.01139 — Granular repeat-sales indexes with spatial pooling (Australia)](https://arxiv.org/abs/2512.01139)
- [JREFE 2023 — Census-tract house price indexes via spatial dynamic factors](https://link.springer.com/article/10.1007/s11146-023-09957-w)
- [IAAO JPTAA — Review of vertical equity measures](https://researchexchange.iaao.org/jptaa/vol20/iss2/7/)
