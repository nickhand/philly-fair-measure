# Source Inventory

Verified inventory of public datasets for the Philadelphia property assessment
project. **Every "verified" entry below was checked live against the source API
on 2026-07-02** (schema via `SELECT * ... LIMIT 0`, row counts via `count(*)`,
ArcGIS layers via service metadata + `returnCountOnly` queries). Nothing here is
assumed from memory or documentation alone. Row counts drift as sources update;
treat them as of the verification date. Update cadence is mostly *unobserved* so
far, establishing it empirically is what the snapshot program is for: the
current-only tables are re-captured monthly by a scheduled workflow that
archives raw parquet to S3 and commits a change summary to `docs/snapshots/`
(see [docs/snapshots/README.md](snapshots/README.md)).

Two API families serve this project:

| Family | Endpoint | Serves |
|---|---|---|
| CARTO SQL API | `https://phl.carto.com/api/v2/sql?q=<sql>` | Tabular city datasets (OPA, L&I, Revenue) |
| ArcGIS REST (City of Philadelphia org) | `https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/<name>/FeatureServer/0` | Parcel/boundary/footprint geometries |

CARTO notes (verified by probing): every table carries an indexed `cartodb_id`
(int8) suitable for keyset pagination; geometry columns (`the_geom`) return as
hex-encoded EWKB strings in SRID 4326; `the_geom_webmercator` is a redundant
CARTO-internal reprojection. ArcGIS layers cap responses at `maxRecordCount=2000`,
so bulk geometry pulls need `resultOffset` paging or envelope tiling.

---

## Core datasets (verified, snapshot-priority)

### 1. OPA property assessments, current roll (`opa_properties_public`)

- **Source page:** <https://opendataphilly.org/datasets/property-assessments/>
- **API:** CARTO, table `opa_properties_public`
- **Rows:** 583,711 (2026-07-02), one row per OPA account (`parcel_number`)
- **Schema:** 82 columns: identifiers (`parcel_number`, `pin`, address parts,
  `registry_number`), current assessment (`market_value`, `taxable_land`,
  `taxable_building`, `exempt_land`, `exempt_building`, `assessment_date`,
  `market_value_date`, `homestead_exemption`), characteristics (`total_livable_area`,
  `total_area`, `frontage`, `depth`, `number_of_bedrooms`, `number_of_bathrooms`,
  `number_stories`, `year_built`, `year_built_estimate`, `quality_grade`,
  `exterior_condition`, `interior_condition`, `basements`, `central_air`,
  `garage_spaces`, `type_heater`, `fireplaces`, `view_type`, `topography`,
  `parcel_shape`, `zoning`, `building_code(_new)`, `category_code`), last sale
  (`sale_date`, `sale_price`, `recording_date`, `book_and_page`), owner/mailing
  fields, `census_tract`, point geometry.
- **Keys:** `parcel_number` (9-digit OPA/BRT account, string, preserve leading
  zeros); `pin` also present. **Accounts beginning `88` are condominium-regime
  parcels, NOT only condo units** (user-confirmed prefix 2026-07-03; scope
  measured same day): residential condo units are the 88s with categories
  SINGLE FAMILY (36,459) / MULTI FAMILY (2,945), RES CONDO building codes, 87%
  with `unit` numbers, median 1,119 sqft, but the prefix also covers
  commercial condos (COMMERCIAL 8,584), whole apartment buildings coded
  APARTMENTS > 4 UNITS (3,971; The Drake is a MULTI FAMILY 88 with 677k sqft),
  INDUSTRIAL (3,622), VACANT LAND (5,457), and parking/storage accounts.
  Any "condo = 88" filter needs category + unit-scale-area guards. Condos are
  excluded from the residential model scope and market-signal pools; the
  dedicated condo model covers residential units at 250–12,000 sqft. Category
  note: `MULTI FAMILY` means 2–4-unit duplexed rowhomes/twins (verified from
  building codes); large apartments are the separate `APARTMENTS > 4 UNITS`
  category.
- **Relevance:** The central table: current characteristics + current assessment.
- **Limitations:** **Current-state only**, characteristics reflect the latest
  known values, not values as of past sale dates (the project's core temporal
  caveat; every feature derived from here is `current_only`). Interior/exterior
  condition fields have real variance (profiled 2026-07-02, single-family:
  ~79% code "4", ~21% spread across codes 1–7, <0.1% null), usable as features,
  unlike Cook County's near-constant condition field, and a renovated property
  still coded at the modal value is itself staleness evidence. `quality_grade`
  mixes letter grades (C+, D-) with numeric and S/X codes, a normalization
  case. `year_built_estimate` flags estimated ages. Condition of unpermitted
  renovations not reflected. Timestamp fields contain unparseable garbage
  (observed live: an `assessment_date`-family value with year "206"), which is
  why the raw layer stores temporal columns as verbatim strings and parsing
  happens at staging with per-value status.

### 2. OPA assessment history (`assessments`)

- **Source page:** <https://opendataphilly.org/datasets/property-assessments/>
- **API:** CARTO, table `assessments`
- **Rows:** 7,485,082 (2026-07-02) ≈ 583k accounts × ~13 years
- **Schema:** 11 columns: `parcel_number`, `year`, `market_value`,
  `taxable_land`, `taxable_building`, `exempt_land`, `exempt_building`. No geometry.
- **Keys:** (`parcel_number`, `year`), **not perfectly unique**: the
  2026-07-02 snapshot has 7,485,082 rows but 7,484,963 distinct key pairs
  (119 duplicates). Staging must resolve or flag these.
- **Relevance:** True assessment history, enables year-over-year assessment
  trajectories, reassessment-cycle detection, and staleness analysis without
  waiting for our own snapshots to accrue. Coverage observed: 2013–2027,
  including the future-year roll (2027 values are published in advance).
- **Limitations:** Values only; no historical *characteristics*. `year` is
  varchar. Whether past years are ever restated is unknown, snapshots will
  answer this.

### 3. Real estate transfers (`rtt_summary`)

- **Source page:** <https://opendataphilly.org/datasets/real-estate-transfers/>
- **API:** CARTO, table `rtt_summary`
- **Rows:** 5,110,364 (2026-07-02)
- **Schema:** 51 columns: `document_id`, `document_type` (deeds, mortgages,
  sheriff's deeds, etc.), `document_date`, `recording_date`, `display_date`,
  `grantors`, `grantees` (free text), `cash_consideration`, `other_consideration`,
  `total_consideration`, `assessed_value`, `common_level_ratio`,
  `fair_market_value`, adjusted variants, `opa_account_num`, `property_count`,
  address parts, `condo_name`/`unit_num`, `reg_map_id`, `legal_remarks`,
  `discrepancy`.
- **Keys:** `record_id` is the true unique key (verified: 5,110,364 distinct on
  5,110,364 rows). `document_id` is NOT unique (4,417,176 distinct, multi-parcel
  documents expand to one row per property), and even
  (`document_id`, `opa_account_num`) has ~346k duplicate pairs. Grain profiled
  2026-07-02: among DEED documents, 169,025 (15.4%) have `property_count` > 1
  and 182,167 (16.6%) lack an `opa_account_num` link, both first-class concerns
  for sales validation.
- **Relevance:** The sales backbone for Milestone 4. Maps remarkably well onto
  the CCAO sales-validation template: `document_type` ≈ deed-type exclusions,
  `grantors`/`grantees` → family-sale and legal-entity heuristics,
  `property_count` → multi-parcel exclusion, `total_consideration` vs
  `fair_market_value`/`common_level_ratio` → nominal-sale detection.
- **Limitations:** Includes *all* recorded transfer-tax documents, not just
  sales, deed filtering is mandatory (top types observed: MORTGAGE 1.51M,
  DEED 1.09M, SATISFACTION 858k, ASSIGNMENT OF MORTGAGE 422k; DEED variants
  like "DEED MISCELLANEOUS" and sheriff's deeds need classification during
  staging). Names are messy free text. Consideration can be nominal
  ($1 family transfers).
- **Condo linkage hole (measured 2026-07-03):** `opa_account_num` is null on
  essentially all condo *unit* deeds (0% of Academy House's 408 deeds and
  Symphony House's 21 were linked), which silently removed condos from any
  OPA-keyed sale pool. The unit sits in `street_address` ("… APT 33K") and in
  `unit_num`. Staged deeds recover the link by matching (normalized address,
  normalized unit) against 88-prefix roll accounts, unique keys only:
  100,159 rows recovered all-time, 84% precision proxy on the sliver that
  carries both a native link and a unit token (disagreements are
  within-building near-misses). Recovered rows carry
  `opa_link_source = "address_unit"`.

### 4. L&I building & trade permits (`permits`)

- **Source page:** <https://opendataphilly.org/datasets/licenses-and-inspections-building-permits/>
- **API:** CARTO, table `permits`
- **Rows:** 925,297 (2026-07-02)
- **Schema:** 48 columns: `permitnumber`, `permittype`, `permitdescription`,
  `typeofwork`, `approvedscopeofwork` (free text), `commercialorresidential`,
  `permitissuedate`, `permitcompleteddate`, `certificateofoccupancydate`,
  `status`, `opa_account_num`, `parcel_id_num`, `address`, `censustract`,
  contractor fields, `geocode_x/y`.
- **Keys:** `permitnumber`, near-unique (224 duplicates on 925,297 rows,
  2026-07-02); dedupe or disambiguate at staging. Joins to OPA via
  `opa_account_num`.
- **Relevance:** Renovation/change proxy (CCAO's `char_recent_renovation`
  analog); issue/completion dates give true event timing for temporal features.
- **Limitations:** Only permitted work is visible, unpermitted renovations
  (including the motivating property's) are invisible by construction. System
  migration artifacts likely (`systemofrecord` column); date coverage to be
  profiled.

### 5. L&I code violations (`violations`)

- **Source page:** <https://opendataphilly.org/datasets/licenses-and-inspections-violations/>
- **API:** CARTO, table `violations`
- **Rows:** 1,990,761 (2026-07-02)
- **Schema:** 36 columns: `violationnumber`, `violationdate`, `violationcode`,
  `violationcodetitle`, `violationstatus`, `violationresolutiondate`,
  `casenumber`, case dates/status/priority, `opa_account_num`, `address`,
  `censustract`, `geocode_x/y`, `underappeal`.
- **Keys:** `violationnumber`, near-unique (13 duplicates on 1,990,761 rows,
  2026-07-02); joins via `opa_account_num`.
- **Relevance:** Property-condition and distress proxy with real event dates;
  neighborhood-level distress aggregates.
- **Limitations:** Enforcement intensity varies by area and era, signal
  confounds condition with inspection attention.

---

## Secondary datasets, PROMOTED 2026-07-03 (snapshotted + staged + in models)

Live-profiled before ingestion (schemas, taxonomies, OPA linkage ~99%):

| Table (CARTO) | Rows (2026-07-03) | What we use |
|---|---|---|
| `complaints` | 1,038,931 | L&I complaints 2000+ (`complaintcodename` taxonomy): MAINTENANCE RESIDENTIAL 169k (tenant-reported interior distress), VACANT HOUSE 64k (the only live vacancy feed), exterior maintenance/weeds. True event dates → `evt_` features. |
| `case_investigations` | 2,080,982 | Inspection events (`investigationtype`): PRECOURT 142k = court-escalation severity ladder; HCEU INSP 678k. |
| `business_licenses` | 431,952 | Rental licenses (288k): tenure spans via initial/inactive dates, `owneroccupied`, `numberofunits` → `ten_` features (17.2% of arms-length sales investor-held at sale). |
| `appeals` | 43,149 | L&I + ZBA appeals with decisions. **Decision vocabulary splits by system generation**: legacy rows say GRANTED with a NULL appealtype; new ZBA rows say "Granted" (and often just "Complete"), match grants case-insensitively across boards. *Not* assessment appeals. |
| `real_estate_tax_delinquencies` | ~460k | Current-only delinquency status per OPA account (total due, years owed, sheriff-sale flag) → `dist_tax_*`/`dist_sheriff_sale` features and a screen evidence column. `opa_number` is numeric at source; staging restores the leading zeros. |
| `demolitions` | ~30k | City demolition events (start/completed dates) → `evt_n_demolitions_before`/`evt_demo_days_since` as-of features, and the aerial-change pilot's ground-truth set. |

## Remaining secondary (existence + row count verified; not ingested)

| Table (CARTO) | Rows | Notes |
|---|---|---|
| `unsafe` | 3,076 | Redundant with `caseprioritydesc` severity ladder (verified) |
| `imm_dang` | 131 | Same |
| `li_court_appeals` | 460 | Tiny |
| `trade_licenses` | 49,961 | Contractor licensing; not parcel events |
| `public_cases_fc` | 5,840,358 | 311 tickets; the L&I `complaints` table is the curated, OPA-linked property subset (carries `ticket_num_311`) |
| `real_estate_tax_balances` | 683,926 | **DEAD: tax periods end 2016** (probed 2026-07-03); delinquencies is the live table |
| `opa_properties_public_pde` | 583,711 | Variant of the OPA table | 

Probed and **not present** on CARTO (do not reference): `vacant_indicators_points`,
`real_estate_transfers` (the transfers table is `rtt_summary`),
`li_building_certifications`, `sheriff_sales`, `zoning_appeals`.

---

## Geospatial layers (ArcGIS REST, verified)

Base: `https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/<name>/FeatureServer/0`

| Service | Geometry | Features | Key fields | Relevance / notes |
|---|---|---|---|---|
| `DOR_Parcel` | polygon | 607,816 | `mapreg`, `basereg`, `parcel`, address parts | Legal (Dept. of Records) parcel fabric. Registry keys ≠ OPA accounts; DOR↔OPA linkage is nontrivial and must go through PWD parcels or AIS. |
| `PWD_PARCELS` | polygon | 547,321 | `brt_id`, `num_brt`, `num_accounts`, `gross_area`, `pin`, owner, `bldg_code` | **Best parcel↔OPA bridge**: carries OPA/BRT account ids directly; `num_brt`/`num_accounts` expose multi-account parcels (the house + side-yard case). Also the geometry source for parcel-shape features. |
| `LI_BUILDING_FOOTPRINTS` | polygon | 546,070 | `bin`, `parcel_id_num`, `approx_hgt`, `max_hgt`, `square_ft` | Building footprints with heights; footprint-change detection across snapshots. |
| `Census_Tracts_2020` | polygon | 408 | `GEOID` | Join key for ACS features. `Census_Tracts_2010` also available for older vintages. |
| `Zoning_BaseDistricts` | polygon | 29,205 | `code`, `long_code`, `zoninggroup`, `pending` | Zoning base districts *are* available as geometry. Dated historical variants exist (`zoning_basedistricts_122019` … `122025`), a ready-made zoning time series. A `zoning_descriptions` service also exists (unverified). |
| `Philadelphia_Neighborhoods` | polygon | 57 | `id` only, **no name field** | ⚠️ Weak: 57 unnamed polygons; likely *not* the canonical neighborhood layer (the widely used Azavea-derived layer has ~158 named neighborhoods). Needs vetting before any use; treat as unverified-for-purpose. |

---

## Verified-but-external (fetch via other APIs when needed)

- **ACS 5-year tract estimates**, Census Bureau API; CCAO's feature list shows
  which tract aggregates earn their keep. Not yet probed; well-documented public API.
- **PhilaDox deed documents**, document images/metadata behind `rtt_summary`;
  access constraints unverified. Investigation milestone, not a dataset yet.

## Deliberately not yet inventoried

Flood risk, transit/GTFS, crime, 311, school catchments, imagery. Each needs the
same live verification before entering this document. CCAO's experience suggests
crime and FEMA flood add little once location and income context are in the
model; prioritize accordingly.

---

## Cross-dataset key map (working hypothesis, validate during staging)

```
opa_properties_public.parcel_number  ==  assessments.parcel_number
                                     ==  permits.opa_account_num
                                     ==  violations.opa_account_num
                                     ==  rtt_summary.opa_account_num
                                     ==  PWD_PARCELS.brt_id
DOR_Parcel.mapreg   ~  rtt_summary.reg_map_id   (registry map ids)
LI_BUILDING_FOOTPRINTS.parcel_id_num  ~  DOR parcel linkage (source-dependent)
census_tract fields  ->  Census_Tracts_2020.GEOID (format normalization needed)
```

All identifiers are strings with meaningful leading zeros, never cast to int.
