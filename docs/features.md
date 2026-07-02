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
- **ACS tract aggregates** — planned, not yet built (needs the Census API
  fetcher); will be tested with/without given AGENTS.md's proxy caution, and
  fairness diagnostics stay separate from the valuation target.
- **Proximity distances** (transit/parks/water/roads) — planned; needs the
  ArcGIS/GTFS fetchers.
- **Parcel-shape metrics** — planned; needs PWD/DOR parcel polygon ingestion.
- **Imagery** — later-stage per the project brief.

## Provenance

Informed by: `docs/ccao-lessons.md` (their production feature table, their
negative results, the condo rolling-average design), live profiling recorded in
`docs/source_inventory.md`, and AGENTS.md's temporal/missingness/interpretability
constraints. Features earn their place empirically from here: cross-validation
by geography and time (Milestone 6) prunes this list.
