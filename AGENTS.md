# Philadelphia Property Assessment / Valuation Project Brief

## Project goal

Build a public-data-driven property assessment and valuation system for Philadelphia, starting with a strong data package and eventually supporting better valuation modeling, comp analysis, and assessment-error detection.

The motivating use case is estimating the value of a renovated Philadelphia row home and understanding whether the city’s OPA assessment is stale or wrong. Longer term, the project should become a general-purpose Philadelphia property valuation framework that can compare against OPA assessments and identify properties whose assessments appear inconsistent with public evidence.

The project should be approached as a combination of:

* Bayesian/statistical modeling
* Python data engineering
* Public records analysis
* Property assessment methodology
* Practical civic-tech product development

The agent should behave like both a Bayesian stats expert and a senior Python data engineer.

---

## Important user/project context

The user bought a Philadelphia row home plus an adjacent side yard in 2023 for about $405k. The purchase involved two lots. They then completed a substantial renovation of about $150k, including a full gut to the studs and adding a bathroom. There were no permits for the renovation. The user believes the side yard and renovation are not reflected well in automated estimates or OPA data.

A key issue: public data likely contains only the latest property characteristics, not historical property characteristics as-of each sale date. This is a central modeling limitation.

The project is not just about one home. The goal is to build a repeatable public-data package and modeling framework for Philadelphia.

---

## Core hypotheses

1. OPA assessments may be stale or miss important changes, especially renovations, side yards, lot combinations, interior condition, and unpermitted work.

2. A public-data model may be able to outperform OPA for some properties, but there are hard limits because important property characteristics are missing, stale, or only available at the current point in time.

3. Snapshotting public datasets over time is a major value-add. Even if historical characteristics are missing today, collecting regular snapshots now creates a future time series.

4. Comp sales remain central. If the assessment board primarily cares about comparable sales, the model should help identify, filter, adjust, and explain comps rather than only output a black-box valuation.

5. The best first step is not modeling. The best first step is building a reliable, reproducible, versioned data package.

---

## Major caution

Do not invent OpenDataPhilly datasets or assume old dataset names/schemas are valid.

The user already noticed that some prior dataset suggestions were outdated or made up, and that “zoning descriptions” were not actually available as previously claimed. The agent should verify every data source directly from OpenDataPhilly, CARTO metadata, City APIs, or source documentation.

For every dataset used, record:

* source URL
* API endpoint
* dataset/table name
* schema
* last updated date, if available
* fetch timestamp
* row count
* geographic coverage
* primary keys or candidate keys
* known limitations

---

## Data architecture direction

Start by building a data package.

Preferred architecture:

* Python project
* DuckDB for local analytical querying
* Parquet for stored tables
* S3-compatible object storage eventually, but local filesystem is fine for the first version
* Raw snapshots preserved separately from cleaned/normalized tables
* Manifests for every fetch
* Reproducible ingestion functions
* Clear distinction between raw, staged, normalized, and modeled data

Suggested layers:

```text
data/
  raw/
    source=<source_name>/
      dataset=<dataset_name>/
        fetched_at=<timestamp>/
          data.parquet
          manifest.json
  staged/
  marts/
  models/
```

Use DuckDB as the analytical engine over Parquet. Consider Polars for fast local data manipulation, especially for large files, lazy scans, and transformations. Pandas is fine for small exploratory work, but the agent should design around larger datasets.

---

## Snapshotting strategy

Snapshotting is a core feature, not an implementation detail.

The project should capture changes over time in public data, especially property characteristics, assessments, permits, violations, sales records, and parcel data.

Recommended approach:

1. Start with full snapshots.
2. Store each snapshot as compressed Parquet.
3. Add a manifest with fetch metadata.
4. Compute row-level hashes to detect changes.
5. Later add change tables/deltas once the raw snapshot process is stable.

Do not prematurely optimize away full snapshots. Storage costs may matter for very large datasets, but compressed Parquet plus partitioning should be manageable for the early version.

Eventually create change tables like:

```text
property_characteristics_changes
assessment_changes
permit_changes
parcel_changes
```

Each change record should ideally include:

* entity ID
* source dataset
* field name
* old value
* new value
* first_seen_at
* last_seen_at
* snapshot timestamp

---

## Temporal alignment problem

A major modeling challenge is that datasets update at different frequencies and represent different effective dates.

Examples:

* sales happen on a transaction date
* assessments may be annual or periodic
* permits have issue dates, completion dates, and statuses
* violations have open/closed dates
* property characteristics may only show current values
* parcel geometries may change over time
* satellite imagery has acquisition dates

For modeling a sale, features should be built “as of” the sale date whenever possible.

Rules:

* Never use future information for a historical sale.
* Track `observed_at`, `effective_date`, and `fetched_at` separately when possible.
* If only current property characteristics are available, mark them as current-only and avoid treating them as historically accurate.
* Build feature tables that explicitly encode temporal assumptions.

Example feature columns:

```text
feature_value
feature_observed_at
feature_effective_date
feature_source
feature_temporal_quality
```

Possible `feature_temporal_quality` values:

```text
as_of_sale
before_sale
after_sale
current_only
unknown
```

---

## Missing data strategy

Missingness is expected and should be modeled carefully.

Do not blindly impute everything.

For each feature, track:

* whether the value is missing
* whether it is structurally missing
* whether it is unavailable from the public source
* whether it failed normalization
* whether it is known but not applicable

Best practice:

* Preserve raw values.
* Add normalized values.
* Add parse/normalization status fields.
* Add missingness indicators.
* Do not overwrite raw values.

Example:

```text
raw_state
normalized_state
state_normalization_status
```

Possible normalization statuses:

```text
ok
missing
invalid
ambiguous
not_applicable
```

This same pattern applies to property classes, land use, zoning-like fields, addresses, sale validity, owner names, document types, and other messy public records.

---

## Feature selection strategy

Do not start with automated feature selection only.

Use a staged approach:

1. Start with assessment-domain features that should matter.
2. Add location, parcel, sale, permit, violation, neighborhood, and spatial features.
3. Use exploratory models to identify predictive features.
4. Use cross-validation by geography and time.
5. Compare model performance against OPA assessments.
6. Keep interpretability as a first-class concern.

Potential evaluation goals:

* sale price prediction error
* assessment-to-sale ratio
* coefficient of dispersion
* price-related differential
* spatial error patterns
* fairness/equity diagnostics if demographic or neighborhood proxies are involved

---

## Modeling direction

A Bayesian hierarchical model is a good fit.

The model should allow partial pooling across neighborhoods, property types, time periods, and possibly school catchments or market areas.

Potential model structure:

```text
log_sale_price ~
  property_features +
  lot_features +
  building_features +
  location_effects +
  time_effects +
  permit/renovation signals +
  spatial effects +
  neighborhood random effects
```

Useful hierarchy candidates:

* census tract
* neighborhood
* ZIP code
* OPA geographic unit, if available
* property type
* building style
* time period / sale quarter

The model should start simple. First baseline could be:

1. repeatable sales-cleaning pipeline
2. hedonic regression or gradient boosting benchmark
3. Bayesian hierarchical model
4. comp-based explanation layer

The project should not jump directly into MCMC before the data package is stable.

---

## OPA comparison

The project should compare model predictions against OPA assessments.

Possible comparison metrics:

* sale price vs OPA market value
* model estimate vs sale price
* model estimate vs OPA
* OPA assessment ratio by neighborhood/property type
* properties where model and OPA strongly disagree
* properties with likely stale characteristics
* properties with signs of renovation not reflected in assessment

However, the agent should avoid overstating that the model will beat OPA everywhere. With public-only data, the model may be better in some cases and worse in others.

---

## Comp sales emphasis

Because assessment appeals often rely heavily on comparable sales, the system should eventually produce comp-style evidence.

Potential comp module:

* find nearby sales
* filter by sale validity
* filter by property type
* filter by date window
* adjust for time
* adjust for size, lot, condition proxies, bathrooms, bedrooms, parking, side yard, etc.
* rank comps by similarity
* explain why each comp was included or excluded

This should be designed as an interpretable output, not just a nearest-neighbor query.

---

## Cook County sales validation idea

The user asked about translating Cook County’s sales validation process to Philadelphia.

The agent should study the Cook County model-sales-val approach and adapt the concepts, but not assume equivalent data exists in Philadelphia.

Potential Philadelphia sales validation work:

* identify arms-length sales
* exclude nominal sales
* exclude sheriff/tax/foreclosure-related sales where identifiable
* identify multi-parcel sales
* identify related-party transfers where possible
* detect suspicious outliers
* use deed/document metadata if available
* compare sale price to assessments and nearby comps
* create a sale-validity label or score

This likely requires combining public sale records with deed/document metadata, and possibly PhilaDox.

---

## PhilaDox / document extraction idea

PhilaDox may be useful for extracting property information from forms and recorded documents.

Potential uses:

* deed records
* transfer documents
* multi-parcel sale detection
* grantor/grantee information
* document type
* sale validation clues
* possibly renovation or characteristic signals, depending on available documents

Approach:

1. Identify available documents and search/access constraints.
2. Determine whether bulk access is possible.
3. Sample documents manually.
4. Build a small extraction pipeline only after confirming document value.
5. Use OCR or structured extraction if documents are PDFs/images.
6. Store extracted fields with provenance and confidence.

Do not assume PhilaDox is easy to scrape or legally/technically suitable for bulk extraction. Verify terms, access limits, and data quality.

---

## Solving the historical characteristics problem

This is one of the hardest problems.

Public property characteristics may only reflect the latest known values. That creates leakage if current features are used to model old sales.

Possible mitigation strategies:

1. Start snapshotting now.
2. Use permits as renovation/change proxies.
3. Use assessment history if available.
4. Use sale listings if legally and practically available.
5. Use deed/document signals.
6. Use imagery-derived changes where feasible.
7. Treat current-only features explicitly as noisy/current-only.
8. Limit some models to recent sales where current characteristics are less stale.
9. Build sensitivity analyses with and without current-only features.

The agent should not pretend this is fully solvable with public data. It is a known limitation.

---

## Satellite imagery idea

The user asked about up-to-date satellite imagery for Philadelphia.

Imagery may eventually help detect:

* building footprint changes
* roof changes
* additions
* demolition
* vacant lot changes
* yard/impervious surface changes
* construction activity
* property condition proxies

Potential sources include public aerial imagery, NAIP, city imagery if available, and commercial satellite/aerial providers. The agent should verify current availability, dates, licensing, resolution, and API access before recommending a source.

If imagery is acquired, the workflow should be:

1. confirm image date and resolution
2. georeference or use already georeferenced imagery
3. tile imagery
4. join to parcels/building footprints
5. extract parcel-level features
6. compare across image dates
7. store features with imagery acquisition date

Imagery should be treated as a later-stage enhancement, not the first milestone.

---

## OpenDataPhilly / CARTO API

OpenDataPhilly appears to expose many datasets through CARTO or similar APIs.

The agent should build generic download utilities that can:

* fetch metadata
* query table schemas
* paginate through large datasets
* export to Parquet
* preserve raw data
* record manifests
* support incremental/snapshot fetches
* handle geometry fields
* handle API limits and retries

The user specifically asked what a download function might look like for the CARTO API. The first implementation should probably be a reusable Python module that can fetch a known table to Parquet and record metadata.

Avoid hard-coding too many assumptions until actual schemas are verified.

---

## Potential data source categories

Verify all specific datasets before using.

Likely useful categories:

* property assessments
* property characteristics
* parcels
* building footprints
* real estate transfers/sales
* permits
* licenses and inspections
* violations
* demolitions
* vacant properties/lots
* unsafe structures
* 311 requests
* tax delinquency, if available
* sheriff sale / foreclosure indicators, if available
* geographic boundaries
* census/ACS demographic and economic context
* transit/accessibility
* flood/environmental risk
* school catchment or public school geography, if relevant and available
* crime/public safety context, used carefully
* aerial/satellite imagery

Do not use sensitive or proxy-heavy features casually. For assessment modeling, be especially careful with features that may encode race, income, or protected-class proxies. If used for diagnostics, separate that from valuation prediction.

---

## Suggested Python project structure

```text
property-assessments/
  AGENTS.md
  README.md
  pyproject.toml
  src/
    philly_fair_measure/
      __init__.py
      config.py
      sources/
        opendataphilly.py
        carto.py
        phila.py
      ingest/
        snapshots.py
        manifests.py
        parquet.py
      normalize/
        addresses.py
        parcels.py
        sales.py
        property_classes.py
      features/
        temporal.py
        spatial.py
        comps.py
      models/
        baseline.py
        bayesian.py
      validation/
        sales.py
        opa.py
      cli.py
  tests/
  notebooks/
  data/
    raw/
    staged/
    marts/
```

Preferred development style:

* type hints
* clear dataclasses or Pydantic models for configs/manifests
* deterministic tests where possible
* small reusable functions
* no hidden manual steps
* source metadata captured automatically
* avoid notebooks as the main pipeline

---

## Initial milestones

### Milestone 1: Verified source inventory

Build a real source inventory from OpenDataPhilly and other official sources.

Deliverable:

```text
docs/source_inventory.md
```

For each source:

* name
* source URL
* API endpoint
* update frequency
* last updated date
* schema
* row count
* key fields
* geometry type
* relevance
* limitations

This must be verified, not guessed.

### Milestone 2: Generic snapshot downloader

Build a downloader for CARTO/API-backed datasets.

Deliverable:

```text
src/philly_fair_measure/sources/carto.py
src/philly_fair_measure/ingest/snapshots.py
```

Capabilities:

* fetch table
* paginate if needed
* save Parquet
* write manifest
* include fetched timestamp
* include row count and schema
* retry failures

### Milestone 3: Local DuckDB catalog

Create a local DuckDB database or query layer over Parquet snapshots.

Deliverable:

```text
src/philly_fair_measure/catalog.py
```

Capabilities:

* register latest snapshot for each dataset
* query raw snapshots
* query normalized tables
* inspect schemas
* join core property tables

### Milestone 4: Sales validation prototype

Build the first sale-cleaning pipeline.

Deliverable:

```text
src/philly_fair_measure/validation/sales.py
```

Start with whatever fields are actually available. Do not overfit to Cook County assumptions.

Output:

```text
sale_id
parcel_id
sale_date
sale_price
validity_status
validity_reasons
confidence
```

### Milestone 5: First feature table

Create a parcel/property feature table for recent sales.

Deliverable:

```text
marts/sale_features.parquet
```

Must include temporal-quality flags for features.

### Milestone 6: Baseline model

Build a simple baseline model before any complex Bayesian model.

Options:

* log-price linear model
* regularized regression
* gradient boosting benchmark
* simple comp-based estimator

Evaluate against sale prices and OPA values.

### Milestone 7: Bayesian hierarchical model

Only after the pipeline is stable, build a Bayesian model with partial pooling by geography/property type/time.

---

## First concrete task for the agent

Start by creating a real, verified source inventory and a working downloader for one or two high-value datasets.

Do not start by building the valuation model.

Suggested first deliverables:

1. `docs/source_inventory.md`
2. `src/philly_fair_measure/sources/carto.py`
3. `src/philly_fair_measure/ingest/snapshots.py`
4. `tests/test_carto_download.py`
5. one successful raw snapshot saved as Parquet with a manifest

The agent should report uncertainty clearly and cite source URLs in the inventory.

---

## Non-goals for the first pass

Do not:

* claim the model beats OPA before testing
* invent unavailable datasets
* assume property characteristics are historically accurate
* use current-only features without flags
* jump straight to MCMC
* build a polished app before the data package exists
* ignore sale validity
* collapse raw and normalized values into one field
* discard unparseable values
* use private/paid/terms-restricted data without explicitly identifying access constraints

---

## Design principles

1. Raw data is sacred.
2. Every derived value needs provenance.
3. Time matters.
4. Missingness is information.
5. Public-only data has real limits.
6. Comp sales should be explainable.
7. Snapshotting creates future value.
8. Prefer boring, reproducible data engineering before fancy modeling.
9. Verify every source.
10. Keep the system useful even before the final model exists.

---

## Best framing for the agent

You are helping build a Philadelphia property assessment and valuation data package. Your first priority is verified public data ingestion, snapshotting, provenance, and temporal modeling. The long-term goal is to estimate property values, compare against OPA assessments, identify stale or inconsistent assessments, and support comp-based explanations. Be skeptical of source availability, preserve raw data, avoid temporal leakage, and make meaningful progress through small tested Python modules.
