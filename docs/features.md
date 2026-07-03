# Feature Registry — `marts/sale_features.parquet`

One row per validated arms-length sale (2016+ by default; the full arms-length
pool back to the start of RTT records feeds the rolling windows). Built by
`philly build-features` from staged tables + the sale-validity mart.

Temporal quality follows the AGENTS.md contract. Prefixes encode it:

| Prefix | Temporal quality | Meaning |
|---|---|---|
| `char_` | **current_only** | Today's OPA roll — NOT the property as of the sale date. Leaky for old sales; models need with/without sensitivity runs. |
| `mkt_` | as_of_sale | Computed strictly from *validated arms-length* sales dated before the sale. |
| `evt_` | as_of_sale | Permit/violation events with true dates strictly before the sale. |
| `asmt_` | before_sale | Assessment roll for the sale year (certified in advance). |
| `loc_` | quasi-static | Location identifiers; parcel geography changes rarely. |
| `time_` | as_of_sale | Encodings of the sale date itself. |

Coverage figures below measured on the 2026-07-02 build (209,680 sales).

## Identifiers / target

`sale_id` (rtt record_id), `parcel_id` (OPA account), `sale_date`, `sale_year`,
**`sale_price`** (target).

## Plan-v2 additions (2026-07-02; see feature-plan-v2.md for mechanisms)

| Feature | Definition | Notes |
|---|---|---|
| `time_adj_log` | District price-index adjustment to the reference month (marts/price_index.parquet) | Models train on log(price)+adj and drop time features (OPA practice). Fixed the median-ratio drift: 0.92 → **0.99**. |
| `mkt_knn_log_ppsf` (+`_n`, `_mean_dist_m`) | Distance-weighted mean time-adjusted log $/sqft of ~15 nearest strictly-prior sales, own parcel excluded, quarter-blocked trees | OPA's `SPATIAL` analog. 96.7% coverage, mean neighbor distance 29m; #3 by gain immediately. |
| `mkt_block_roll_ppsf` | $/sqft version of the block rolling mean | Disentangles neighbor size from location value. |
| `mkt_area_level_log_ppsf` | Learned market-area median (time-detrended) log $/sqft | #5 by gain. |
| `loc_market_area`, `loc_district` | Learned GMA analog (350 areas / 18 districts, marts/market_areas.parquet) | OPA's GMAs are PDF-only; boundaries learned from sales embed all-time info (like annually redrawn GMAs). |
| `char_style`, `char_era` | Parsed style (row/twin/detached/other/unknown) and era bands | Enables Keene-style segmented evaluation; style COD gradient matches theirs. |

Explicitly rejected: `off_street_open` — profiled as NOT a parking field
(5,308 distinct values, mean ~2,050; semantics unknown). Parking signal stays
with `garage_spaces`/`garage_type`.

**Distress signals (2026-07-03, the q1 follow-up):** `evt_n_severe_violations_5y_before`
/ `evt_n_open_severe_at_sale` (L&I case priority in HAZARDOUS/UNSAFE/IMMINENTLY
DANGEROUS/UNFIT — as_of_sale), `evt_n_demolitions_before` / `evt_demo_days_since`
(as_of_sale), and `dist_tax_delinquent`/`_years_owed`/`_total_due`/`_sheriff_sale`
(**current_only** — the delinquency table shows today's delinquents). Result:
best overall model to date (RMSE(log) 0.337, R² 0.810, COD 25.8; delinquency
amount/years rank highest among the additions) but the **q1 median ratio stayed
~1.20** — the cheap-tail gradient is dominated by unobservable interior
condition, beyond what public distress records carry. Remaining q1 options are
external (listings — access/terms-constrained; imagery — later-stage) or
accepting the limit and letting the Bayesian intervals carry the tail
uncertainty, which they do.

**L&I distress round two + tenure (`evt_`/`ten_`, 2026-07-03):** four newly
ingested tables (complaints 1.04M, case_investigations 2.08M, rental
business_licenses 288k, appeals 43k — all ~99% OPA-linked, live-profiled
before ingestion). **Vocabulary gotcha (caught by coverage checks):** both
the complaint taxonomy and the appeal decision vocabulary changed with L&I's
~2022 system migration, so every slice needs both eras — the legacy-only
lists produced working totals with silently-zero slices at recent valuation
dates. Features, all as_of_sale: interior-maintenance complaints
(tenant-reported heat/plumbing/sewage — the closest public proxy for
interior condition; 11.7% of sales within 5y), exterior maintenance,
**vacancy complaints + recency** (the only live vacancy feed; 6.9% within
5y), **unpermitted-work complaints** (2.2% — neighbors reporting exactly the
renovations permits miss; the founding use case's signal, also a screen
evidence column), inspections + **PRECOURT escalation** (6%), granted
variances/appeals (any board), and rental-license tenure spans:
**investor-held-at-sale** (17.2%), owner-occupied-landlord flag, licensed
units. **Result: best model to date overall — RMSE(log) 0.3377, COD 26.00
(from 26.18) — but the q1 median ratio stays 1.200 and q1 COD 39.0. The
interior-condition wall does not move.** This closes the public-data attack
on the q1 tail: resident-reported distress is now IN the model and the
residual q1 bias persists, which makes the earlier diagnosis airtight —
what's unobservable is *positive* interior condition (renovation), not
distress. Remaining paths are listings/imagery (see research notes). The
vacancy, unpermitted-work, and tenure columns also feed the screen as
evidence and the equity diagnostics.

**Identical-twin uniformity (`twin_n`, `opa_vs_twin_median` on the screen,
2026-07-03):** Philadelphia's blocks are runs of identical rowhomes, and
Pennsylvania's constitutional **uniformity clause** makes
assessment-vs-comparable-assessments a first-class appeal argument. The
strict twin key requires every recorded characteristic to match on the same
block (area, lot, style, stories, year built, exterior/interior condition,
quality grade, basement, garage, central air). Measured on the current roll:
**40.3% of residential parcels sit in loose characteristic-twin sets of ≥5**
(median within-set assessment spread 26.9% — but mostly explained by
recorded condition differences); **22.6% sit in STRICT sets of ≥5**, where
OPA is largely uniform (77% of sets all-equal, median spread 0.0%) — and the
residue is the sharpest appeal evidence public data can produce: **624
parcels assessed >10% (204 of them >25%) above homes their own records
describe as identical in every respect** (top case: 10× its six twins).
The screen carries `twin_n` and `opa_vs_twin_median` for every parcel in a
strict set; the future report layer should render the twin table as a
uniformity exhibit. OPA-process note: strict-twin uniformity being high is
*to their credit* and worth saying in any public write-up; the loose-twin
spread mostly measures recorded-condition differences, which an appellant
can contest separately if their condition code is wrong.

**Owner-linked adjacency (`shp_n_linked_parcels`, `shp_linked_lot_area_m2`,
2026-07-03):** same-small-owner parcels touching within 0.3m (institutional
owners with >20 parcels excluded) — the house + side-yard assemblage signal.
26,995 linked parcels citywide; negligible in the citywide model (assemblages
are rare) but carried into the assessment screen, where 12,359 residential
properties have linked parcels and 768 of those are also disagreement-flagged.

**Parcel geometry (`shp_`, Tier 2.1, 2026-07-03):** CCAO's shape set computed
from PWD parcel polygons (area, perimeter, vertices, edge-length SD,
interior-angle SD, centroid-distance SD, minimum-rotated-rectangle ratios)
plus `shp_parcel_num_brt`/`num_accounts` via the `brt_id` bridge. Coverage
99.7%. **Honest result: ~no metric movement in Philly** (COD 25.96 vs 26.00) —
rowhome lots are uniform rectangles (mean 6 vertices), so the features that
earn their keep on Cook County's irregular suburban lots have little variance
here (1.9% of model gain). Kept: cheap, mildly helpful on PRD/MAPE, more
relevant for detached segments, and the parcel-polygon snapshots enable future
geometry-change detection regardless.

## Condo model (`marts/condo_sale_features.parquet`, v1 2026-07-03)

Separate model per CCAO practice (`philly build-condo-features` +
`philly train-condo`).

**The v0→v1 story is a data-linkage detective story.** v0 (COD 55.7, "wild
thin market") was trained on the wrong population: RTT leaves
`opa_account_num` null on most condo unit deeds (0% of Academy House's 327
resales were linked), so the 88-linked "condo" sale pool was actually 85%
commercial parcels, whole apartment buildings, and industrial condos. Two
fixes: (1) **condo link recovery** in staged deeds — unlinked deeds matched
to 88 accounts on (normalized address, unit token), 100,159 rows recovered,
precision proxy 84% with within-building near-misses; (2) **scope filters** —
residential roll categories only, unit-scale areas 250–12,000 sqft (The Drake
is a "MULTI FAMILY" 88 account with 677k sqft and a $233M bulk sale), ppsf
20–5,000. Sales validation also now pools condo units separately
(`pool_category = "CONDO UNIT"`) so tower $/sqft doesn't distort rowhome
reference pools; and (3) the roll's own **"RES CONDO" building-code marker**
scopes true units (unit-less "residential" 88s are whole apartment buildings,
condo parking, and nominally-assessed common elements — screening those as
"under-assessed" would be wrong on the merits). Result: **18,688 true condo
unit sales 2014+ (was 747 residential-coded), building-roll coverage
26% → ~95%** — the CCAO design assumption (units in a building price
together) holds in Philly after all; the towers were always there, their
sales were unlinked. Building key stays the measured 30m union-find
clustering of unit geocodes. `char_floor` parsed from unit tokens (2204 → 22)
adds a small gain.

v1 results (2,803-sale out-of-time test): model RMSE(log) 0.279 / R² 0.82 /
COD 22.5 / PRD 1.03 vs OPA 0.278 / 0.82 / **18.8** / 1.03 — a statistical
tie on log-accuracy; OPA wins ratio dispersion. **Retraction:** v0's "OPA
assesses condos at a median 75% of sale price" finding was an artifact of
the contaminated pool (bulk building sales vs income-approach assessments).
On true condo units OPA's median ratio is 0.91 with COD 19 — **condos are
OPA's best-assessed segment**, far better than their rowhome COD ~33. The
equity asymmetry is therefore *between* segments: the condo-owning
(affluent-skewing) stock gets accurate, slightly-under assessments while
cheap rowhomes get severely dispersed, regressive ones.

**Screen integration:** `philly screen-assessments` now scores every RES
CONDO unit (250–12,000 sqft) alongside residential — point estimate from the
condo run, 90% interval from spatially weighted conformal offsets
(`interval_method="conformal_knn"`; the condo model has no Bayesian arm).
The screen mart gained `model_family` and neutral column names
(`model_median`/`model_pi_low_90`/`model_pi_high_90`). First screen: 32,153
condo units, 861 over- / 4,085 under-assessed candidates (median OPA/model
0.928, matching the test-set OPA ratio); flagged leads include a 320 sqft
unit assessed at $858k (OPA data error) and $29k assessments on 2,400 sqft
Society Hill units.

## Market signals (`mkt_`) — informed by CCAO's condo model

| Feature | Definition | Notes |
|---|---|---|
| `mkt_block_roll_mean_price` | Leave-one-out, time-weighted mean of prior arms-length sales on the same block (same `street_code`, same 100-number block), other parcels only, 5-year window, logistic decay (w=0.95 at 0y, 0.5 at 3y, 0.12 at 5y) | The rowhome transplant of CCAO's building-level rolling mean. Coverage 96.5%, avg 8.6 peers. **corr(log price) ≈ 0.81 — stronger univariately than the assessment itself (0.71).** Main defense against unobservable interior condition. |
| `mkt_block_roll_n` | Number of peer sales in that window | Reliability weight for the mean. |
| `mkt_parcel_n_prior_sales` | Prior arms-length sales of this parcel (all-time) | 57.1% of sales are repeats. |
| `mkt_parcel_prev_price`, `mkt_parcel_days_since_prev` | Most recent prior sale of the parcel | Repeat-sales signal; flip context. |

## Characteristics (`char_`) — informed by CCAO's res-model feature table + our profiling

`char_livable_area`, `char_lot_area`, `char_frontage`, `char_depth`,
`char_beds`, `char_baths`, `char_rooms`, `char_stories`, `char_year_built`,
`char_basement`, `char_central_air`, `char_garage_spaces`, `char_fireplaces`,
`char_heater`, `char_construction`, `char_view`, `char_topography`,
`char_category`, `char_building_type`, `char_zoning_raw`,
`char_quality_grade_raw`, and — diverging from CCAO's exclusion, on evidence —
`char_exterior_condition` / `char_interior_condition` (Philly's condition codes
are ~21% non-modal vs Cook County's ~98%-constant field, so they carry signal;
a renovated property still coded at the modal value is itself staleness
evidence). `_raw` suffixes mark fields still needing normalization
(quality_grade mixes letter/numeric/S/X codes).

**Interior-condition reality check (measured 2026-07-03, user hypothesis:
OPA has no interior inspectors):** confirmed with nuance. 81.8% of
residential parcels carry interior == exterior (the modal cell, 4/4
"average", holds 351,608 parcels), and among **67,015 parcels with major
renovation permits since 2020 — the one paper trail that tells OPA an
interior changed — 77.5% still have interior == exterior and only 17% show
interior coded better.** The field is mostly an exterior echo with ~18%
genuine off-diagonal information; true interior state is unobserved, which
(a) makes the q1 interior-condition diagnosis airtight from the OPA side
too, (b) means interior-condition-based assessment differences between
otherwise-identical twins rest on a field OPA cannot verify (appeal-relevant
in both directions), and (c) splits the imagery roadmap cleanly: Mapillary
facades check the code OPA actually maintains (exterior); only listings
photos can see interiors.

## Events (`evt_`) — true event dates, no future leakage (tested)

| Feature | Definition |
|---|---|
| `evt_n_permits_5y_before` | L&I permits issued in the 5y strictly before the sale (18.7% of sales have ≥1) |
| `evt_days_since_last_permit` | Days since most recent permit before the sale (any age) |
| `evt_n_violations_5y_before` | Violations opened in the 5y strictly before the sale |
| `evt_n_open_violations_at_sale` | Violations open (unresolved) on the sale date |

Known limitation: unpermitted work is invisible by construction — permit
features help the citywide model, not properties renovated without permits.

## Assessment (`asmt_`) — Philly-specific advantage (15y history table)

| Feature | Definition |
|---|---|
| `asmt_market_value_sale_year` | OPA market value for the sale year (98.8% coverage) |
| `asmt_value_yoy_change` | Change vs the prior year's roll — reassessment-jump signal |

## Location (`loc_`) and time (`time_`)

`loc_lon`/`loc_lat` (+`loc_lonlat_status`; decoded from EWKB, 99.9% ok),
`loc_zip5`, `loc_census_tract_raw`, `loc_ward`, `loc_street_code`,
`loc_block_id`. `time_quarter`, `time_month`, `time_weekday`.
The location IDs double as the partial-pooling hierarchy for the Milestone 7
Bayesian model.

## Deliberately excluded (with reasons)

- **Crime** — CCAO: collinear with income/location, unreliable aggregation.
- **FEMA flood zones** — CCAO: ~zero contribution once coordinates + flood-risk
  scores exist; we skip flood entirely for now.
- **School ratings** — CCAO dropped them in 2025.
- **ACS tract aggregates** — measured, excluded (2026-07-03): the
  `philly acs-sensitivity` diagnostic retrain shows tract demographics carry
  1.15% of gain and move NO metric (overall, q1, or any majority-race group)
  beyond noise — the learned spatial machinery subsumes them. The legal ban
  costs nothing; demographics remain diagnostics-only by design AND by
  measurement (docs/equity-diagnostics.md).
- **Imagery** — later-stage per the project brief.

## Proximity (`prox_`/`loc_street_class`, 2026-07-03 — the last OPA-parity family)

`philly build-proximity` → `marts/proximity.parquet` (quasi-static,
per-parcel; joined into all three feature builds). Sources live-verified:
SEPTA's ArcGIS org (BSL 24 + MFL 28 rapid-transit stations, 155 regional-rail
stations), city PPR_Properties (506 park polygons), city Street_Centerline
(41,271 segments; `st_code` joins OPA street_code 100%). Features: distance
to nearest rapid-transit station / regional-rail station / park boundary
(0 inside) / expressway (class 1, a disamenity) / arterial (class 2-3), plus
`loc_street_class` (modal class of the parcel's own street, categorical).
Median parcel: 1.4km to rapid transit, 231m to a park, 107m to an arterial.
**Honest result: 0.68% of model gain, COD 26.29 → 26.18, condo a wash** —
same verdict as parcel shapes: the kNN sale surface + market areas already
price location; kept because cheap, interpretable, and closing OPA variable
parity.

## Provenance

Informed by: `docs/ccao-lessons.md` (their production feature table, their
negative results, the condo rolling-average design), live profiling recorded in
`docs/source_inventory.md`, and AGENTS.md's temporal/missingness/interpretability
constraints. Features earn their place empirically from here: cross-validation
by geography and time (Milestone 6) prunes this list.
