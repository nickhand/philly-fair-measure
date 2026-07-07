# Lessons from the Cook County Assessor's Data Department (ccao-data)

Distilled from reading the READMEs of all 30 repos in <https://github.com/ccao-data>
(reviewed 2026-07-02). CCAO is the closest thing to a reference implementation for
this project: a small team doing open-source, reproducible mass appraisal with
LightGBM, dbt, and heavy provenance discipline. They operate *inside* the assessor's
office with system-of-record access; we operate *outside* with public data only, and
OPA is our benchmark/adversary rather than our employer. Patterns transfer; data
access does not.

## Org map

| Repo | What it is | Relevance here |
|---|---|---|
| `model-res-avm` | Residential AVM (LightGBM, R/Tidymodels), exhaustively documented | Model design, features, CV, provenance, the core reference |
| `model-condo-avm` | Condo AVM | Playbook for valuing property with missing characteristics |
| `model-sales-val` | Non-arms-length sale flagging (Python) | Direct template for Milestone 4 sales validation |
| `data-architecture` | dbt + Athena lakehouse: transforms, tests, docs, freshness checks | Template for our staged/marts layers (dbt-duckdb analog) |
| `service-spark-iasworld` | System-of-record → Hive-partitioned Parquet → S3 → Athena mirror | Validates our raw snapshot design (CARTO → Parquet → DuckDB) |
| `assesspy` / `assessr` | Ratio study stats: COD, PRD, PRB, MKI, sales chasing | `pip install assesspy`, use directly, don't reimplement |
| `ccao` | Data dictionary + rename/recode utilities as package data | Pattern for our normalize layer |
| `homeval` | Static per-PIN report: characteristics, comps, SHAPs (Hugo) | Endgame for comp-based explanations |
| `ptaxsim` | R package + versioned SQLite DB of tax bills 2006–2024 | Distribution pattern: versioned data artifact + query package |
| `extract-permits` | Scheduled GH Actions pull of Chicago permits (date-ranged) | Same shape as our L&I permit ingestion |
| `lightsnip` | LightGBM ↔ Tidymodels glue (early stopping, linked params) | Confirms LightGBM as engine; Python has native equivalents |
| `service-alerts` | Alert when scheduled AWS jobs don't produce expected logs | Snapshot cron needs "did it actually run" alerting |
| `api-res-avm` | REST API serving predictions by model `run_id` | Later; note run_id-addressable models |
| `report-model-benchmark` | LightGBM vs XGBoost timing benchmark | LightGBM won on speed at similar accuracy |
| others (`wiki`, `public`, `people`, `actions`, shiny/nginx services) | Docs, engagement, internal infra | Low relevance |

## Architecture patterns worth copying

1. **Raw 1:1 mirror first.** `service-spark-iasworld` extracts source tables verbatim
   to Hive-partitioned Parquet on S3, queried via Athena. No transformation at ingest.
   Our analog: CARTO/ArcGIS → `data/raw/source=.../dataset=.../fetched_at=.../*.parquet`
   → DuckDB. Post-load, they trigger validation (dbt tests), our manifests should
   record row counts/schema and a validation pass should follow each snapshot.
2. **dbt as the transform + test + docs layer.** All staged/mart tables are dbt models
   with schema tests, daily test runs, source-freshness checks, and an auto-generated
   public data catalog. Analog: `dbt-duckdb` once we have more than a couple of staged
   models; before that, plain SQL views are fine. Their catalog docs
   (<https://ccao-data.github.io/data-architecture>) are also the best reference for
   *what* they compute (e.g. `model.vw_card_res_input`).
3. **`run_id` on everything.** Every model run gets a unique run ID; all outputs
   (values, comps, SHAPs, performance, hyperparameters, timings, git SHA, DVC hash of
   inputs) are stored keyed by `(year, run_id)` in perpetuity. Sales-val flags carry
   `run_id` + a per-sale `version` that increments on re-flagging. Adopt from day one,
   it is cheap early and impossible to retrofit.
4. **params.yaml + DVC pipelines.** One YAML controls every stage; DVC tracks
   stage dependencies, caches unchanged stages, and versions input data on S3.
   Adopt DVC when the modeling pipeline exists; snapshots have their own manifest
   system and don't need it.
5. **Publish reproducible inputs.** They post each year's training/assessment Parquet
   publicly. Our snapshots serve the same role: immutable, manifested, never edited.
6. **Automation with heartbeat alerting.** Scheduled GH Actions run extraction, dbt
   tests, and freshness checks daily; `service-alerts` fires when an expected job
   produced no logs. A snapshot cron that silently dies is worse than none.

## Sales validation (`model-sales-val`), template for Milestone 4

Mechanics:

- Assign each sale to a **statistical group**: geography × property class × rolling
  time window. Compute group mean/SD of **log(price)** and **price per sqft**.
  Flag beyond N standard deviations (both directions).
- **Pre-exclusions** before grouping: sales < $10k, multi-PIN sales, duplicate price
  for same parcel within 365 days.
- **Heuristic flags** (supplementary, they do NOT alone set `is_outlier`; only
  price-deviation reasons do): family sale (buyer/seller last-name match), non-person
  legal entity keywords (LLC, bank, builder, trust...), short-term owner, price swing +
  short hold ("flip"), raw price ceiling, transfer-form fields indicating distress
  (PTAX-203 short-sale question → our analog: RTT document type / deed metadata,
  sheriff's deeds), isolation forest as an unsupervised backstop.
- Up to 3 reasons per sale (`outlier_reason1..3`); analyst review supersedes the
  algorithm (added 2026).
- Output tables, all `run_id`-keyed: `flag` (per sale, versioned), `metadata`
  (commit SHA, timestamps), `parameter` (every threshold used), `group_mean`
  (the group stats used, so any flag is fully explainable after the fact).

Philadelphia mapping: `rtt_summary` (5.1M rows on CARTO) carries document type,
consideration/price, grantor/grantee names, and parcel linkage, enough for the
group-stats core plus name-match, entity-keyword, sheriff's-deed, short-hold, and
multi-parcel heuristics. Multi-parcel transfer detection matters personally: the
motivating property was a two-lot purchase.

## Residential AVM (`model-res-avm`)

- **Engine:** LightGBM, chosen over XGBoost/CatBoost/RF/NN/stacking for accuracy,
  speed, and native categorical handling. A **linear baseline is trained alongside**
  every run for comparison. Bayesian hyperparameter search; ~14 tuned params.
- **Pipeline stages** (DVC): ingest → train → assess → evaluate → interpret →
  finalize → upload → export. Each an independent script; each cached.
- **Training data:** 9 years of validated arms-length sales (~400k × ~100 features).
  Deed-type exclusions (quit-claim, executor, related-party, REO/foreclosure),
  multi-PIN and multi-building sales excluded, analyst overrides respected.
- **Temporal hygiene:** out-of-time test set (most recent 10% of sales);
  rolling-origin CV originally, V-fold since 2024; final model retrained on all data;
  assessment = predict every property with sale date set to the lien date (Jan 1).
- **Features** (categories): characteristics (~25 usable of ~40 tracked), ACS5 tract
  aggregates, location IDs (tract, school districts, municipality, neighborhood),
  proximity distances/counts (transit, parks, water, roads + traffic, foreclosures
  per 1000 parcels within ½mi, new construction, stadium...), **parcel-shape metrics
  from polygon geometry alone** (vertex count, edge-length SD, interior-angle SD,
  min-rotated-rect ratios, centroid-distance SD), time encodings, and market signals
  (`meta_sale_count_past_n_years`, `char_recent_renovation` = renovated in last 3 yrs).
- **Deliberate exclusions + why:** property condition (98% identical → no signal),
  crime (collinear with income/location), interior quality (unobservable, same
  problem we have), FEMA flood zones (First Street factor + lat/lon absorbed it).
- **Post-modeling:** multi-card and prorated-PIN aggregation rules, complex-level
  value averaging for near-identical rowhomes/townhomes (fuzzy grouping to stop
  identical units getting different values), round to $1k. Philly analog: handling
  properties spanning multiple OPA accounts (house + side yard).
- **Representativeness checks:** logistic-regression balance tests
  (`sold_in_last_2_years ~ characteristics + location FE`) to detect unrepresentative
  sales samples.
- **Evaluation:** RMSE/MAE/MAPE/R² plus assessor metrics COD/PRD/PRB/MKI, computed by
  geography × class × price quantile, quantile breakouts expose regressivity that
  aggregates hide.
- **Interpretability:** per-property SHAP values, global feature importance, and
  experimental **comps from LightGBM leaf-node co-assignment** (sales that land in
  the same leaves as the target are its comps), feeds `homeval` reports.
- **Transparency posture:** README documents every choice + rationale, an "Ongoing
  Issues" section admits data problems (stale/missing characteristics,
  non-arms-length leakage, disclosure incentives), and FAQs pre-empt "why isn't my
  assessment my sale price" (sales chasing). Emulate this tone in our docs.

## Condo model (`model-condo-avm`), the missing-characteristics playbook

Condos: interiors unobservable, only age/location/sale/% ownership complete. Their fix:

- **Leave-one-out, time-weighted rolling average sale price of the building**
  (5-year window, logistic time decay, excludes the sale being predicted, excludes
  flagged outliers). A spatial-lag feature that tells the model "these units are
  related." They argue it isn't sales chasing because the target sale is excluded.
- % of ownership differentiates units within a building.

Rowhome analog: the same LOO rolling average computed over a block face / street
segment / GTFS-style micro-area. Philly rowhomes are block-homogeneous the way condo
units are building-homogeneous, and our interior-condition blindness is identical.
This is likely the highest-value engineered feature available from sales data alone.

## Measurement (`assesspy`)

Python package implementing IAAO ratio-study statistics: COD, PRD, PRB, MKI, sales
chasing detection. Use it for all OPA-vs-model and OPA-vs-sale comparisons
(Milestone 6+) instead of hand-rolling.

## What we deliberately do differently

- **Public data only**, no iasWorld equivalent. Our raw layer is OpenDataPhilly
  (CARTO SQL API) + city ArcGIS REST, and snapshot history *is* our system of record.
- **DuckDB local, not Athena/AWS**, same Parquet-mirror idea, zero infra.
- **Bayesian hierarchical layer**, CCAO stops at LightGBM point estimates; our added
  value is calibrated uncertainty (a per-property credible interval matters for
  appeal decisions). Keep their LightGBM+linear baseline as the benchmark to beat.
- **Assessment-error detection is the product**, not the assessment roll. CCAO
  compares model to sales; we additionally compare model to OPA to find stale
  assessments.

## Adoption checklist mapped to our milestones

- [ ] M1 inventory: document like their data catalog (source, schema, keys, freshness, limitations)
- [ ] M2 snapshots: Hive-partitioned Parquet mirror + manifest + post-load validation (their spark-extractor pattern)
- [ ] M2+: `run_id` + git SHA + params recorded on every pipeline output
- [ ] M3 catalog: DuckDB views over latest snapshots; adopt dbt-duckdb when staged models multiply
- [ ] M4 sales-val: group-stats (log price, $/sqft) + heuristics + reason codes + versioned flags, adapted to `rtt_summary`
- [ ] M5 features: parcel-shape metrics, ACS5 tract joins, proximity features, sale-count and LOO rolling-average market signals, permit-based `recent_renovation`
- [ ] M6 baseline: LightGBM + linear baseline, out-of-time split, `assesspy` metrics by geography × class × quantile, balance tests
- [ ] M7 Bayesian model evaluated against the same harness
- [ ] Comp layer: leaf-node comps + homeval-style static per-property report
- [ ] Ops: scheduled snapshot workflow + heartbeat alerting ("no logs" = alarm)
