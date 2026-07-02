# Feature Engineering Plan v2

Goal: improve the measured metrics from the v1 baselines. Grounded in OPA's
TY2027 methodology and the 2026 literature (see
[research-notes.md](research-notes.md)); every item states the mechanism by
which it should move a metric.

**Current state (out-of-time test, 19,580 sales):**

| | RMSE(log) | COD | PRD | median ratio | 90% coverage / rel. width |
|---|---|---|---|---|---|
| LightGBM | 0.350 | 25.5 | 1.108 | 0.919 | — |
| Bayesian | 0.426 | 33.4 | 1.138 | 1.118 | 0.913 / 1.60 |
| OPA (same convention) | 0.450 | 34.6 | 1.190 | 0.983 | — |

**Targets for v2:** LightGBM COD ≤ 20 and median ratio ≈ 1.00 ± 0.02;
PRD ≤ 1.05; Bayesian relative interval width ≤ 1.2 at coverage 0.88–0.92,
with coverage holding **by zone and price quintile**, not just overall.
Also add a time-adjusted ratio-study mode to compare with OPA's published
COD 10.1 on equal terms.

---

## Tier 1 — highest expected value, data already on disk

### 1.1 Local monthly market index + time-adjusted prices *(the big one)*
OPA time-adjusts every sale to the valuation date with a compound monthly
index, then drops time from the model. Both our models visibly mis-extrapolate
time instead (0.92 / 1.12 median ratios). Build `marts/price_index.parquet`:
monthly log-price index per **district** (learned market areas from 1.2, with
citywide pooling for sparse cells; medians or repeat-sales flavor per the
granular-index literature). Then:
- train both models on **time-adjusted log prices**, re-inflate at scoring
  time with the index nowcast;
- keep the index level and 12-month momentum as features for the raw-price
  variant (A/B the two designs).
**Mechanism → metric:** removes trend error from every prediction:
median ratio → ~1.0 for both models; COD drops by the drift component;
Bayesian time-overshoot disappears.

### 1.2 Learned market areas (GMA analog)
OPA leans on 600+ hand-maintained GMAs; they are PDF-only (verified). Learn
~200–500 market areas from arms-length sales: cluster on (lon, lat,
time-adjusted $/sqft level) with spatial contiguity (two-stage cluster
approach, arXiv:2508.03156). Emit `loc_market_area` + cluster-level median
$/sqft. Use as: LightGBM categorical, Bayesian hierarchy level
(ward → market_area), and the index geography for 1.1.
**Mechanism:** captures the sub-market boundaries OPA encodes manually —
the largest known location signal we currently lack. COD ↓, tract-level
coverage evens out.

### 1.3 Smooth spatial value surface (OPA's `SPATIAL`, done right)
- LightGBM: k-nearest-sales feature — distance-decayed mean **time-adjusted
  $/sqft of the ~15 nearest arms-length sales** (excluding same parcel),
  computed as-of sale date (kd-tree; leakage-tested like the block roll).
- Bayesian: **HSGP** over (lon, lat) (`pm.gp.HSGP`, ~250 basis functions)
  alongside the discrete hierarchy.
**Mechanism:** boosted trees can't interpolate space smoothly and area dummies
step at boundaries (GP-Boosting literature); a surface fixes between-block
gradients. COD ↓, spatial residual autocorrelation ↓.

### 1.4 Scale-free market features
Add `mkt_block_roll_ppsf` (block roll mean **per sqft**) next to the existing
price-level version, plus block-level median $/sqft. **Mechanism:** current
block roll conflates neighbors' size with location value; per-sqft
disentangles, helping small/large homes at the price tails → PRD ↓.

### 1.5 Structured style + era features
Parse `char_building_type` into style (ROW / TWIN / DETACHED / RANCHER / ...)
and stories; band `char_year_built` into OPA-style eras. OPA models styles
separately and its COD differs by style (singles 6.7 vs rows 10.7) — style
interactions matter. **Mechanism:** COD ↓ within styles; also enables
style-segmented evaluation like Keene's.

### 1.6 Off-street parking × Center City
`off_street_open` (OPA column, currently unused) + garage, interacted with
the Center City market areas — OPA applies parking value only "where
valuable." **Mechanism:** targeted error reduction in the highest-price zones
(our q5 MAPE is 17.6%).

## Tier 2 — new but verified data pulls

### 2.1 PWD parcel polygons (ArcGIS fetcher)
`brt_id` bridge + geometry → parcel-shape features (CCAO's proven set),
corner-lot flag, `num_brt`/`num_accounts` multi-account signal (side yards —
the user's own case). **Mechanism:** lot-quality signal orthogonal to sqft.

### 2.2 Street classification + proximity set
City street centerline classes (arterial vs local — OPA uses "street
classification"), SEPTA GTFS stop distances, park/water distances.
**Mechanism:** micro-location beyond the block roll; known CCAO features.

### 2.3 ACS tract context — diagnostics only
arXiv:2605.15020 shows census context improves accuracy *and* fairness, but
OPA is legally barred from people-data and our valuation model should remain
appeal-comparable. Build as a **toggled feature group**: excluded from the
default valuation model; reported as a sensitivity run; used in equity
diagnostics. **Mechanism:** measures how much accuracy the legal constraint
costs, without contaminating the defensible model.

## Tier 3 — Bayesian model upgrades (modern practice)

1. **Student-t likelihood** (ν learned) — tails stop inflating σ; intervals
   narrow at equal coverage (target rel. width 1.60 → ≤1.2).
2. **Monthly random-walk time effect** (or adopt 1.1's time-adjusted design) —
   kills the linear-trend overshoot.
3. **HSGP spatial surface** (1.3) + hierarchy ward → market area → tract.
4. **Heteroscedastic σ**: log-linear in evidence density (block_roll_n,
   block_roll_missing) and price tier — sharper where data are dense, honest
   where sparse; Case–Shiller models variance explicitly.
5. **Calibration reporting**: coverage + PIT by zone/style/quintile (the
   spatially-weighted-conformal lesson: marginal coverage hides local
   failure); PSIS-LOO for model comparison.
6. **Conformal cross-check**: spatially weighted conformal intervals around
   LightGBM (arXiv:2312.06531) as a frequentist benchmark for the Bayesian
   intervals.

## Evaluation upgrades (so improvements are measurable and comparable)

- **Time-adjusted ratio study mode**: evaluate model and OPA against
  time-adjusted sale prices within a sales window (their convention, COD 10.1)
  *alongside* our out-of-time convention — report both.
- Style-segmented metrics (singles/twins/rows) matching Keene's table.
- Coverage by zone × quintile as a first-class output of every Bayesian run.

## Sequencing

1. Market-area learning (1.2) → monthly index (1.1) → retrain both models on
   time-adjusted prices — biggest single expected jump; everything else layers
   on top.
2. k-NN spatial surface + per-sqft features + style/era (1.3–1.5) → retrain.
3. Bayesian upgrade bundle (Tier 3) with the new features.
4. PWD parcels + street/proximity (2.1–2.2) as the ArcGIS fetcher lands.
5. Evaluation upgrades ship with step 1 (needed to measure it honestly).
