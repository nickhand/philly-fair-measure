# philly-assessments

A public-data-driven property assessment and valuation system for Philadelphia.
The first deliverable is a reliable, reproducible, versioned data package built
from verified OpenDataPhilly sources; valuation modeling, OPA comparison, and
comp analysis come after the data foundation is stable. See [AGENTS.md](AGENTS.md)
for the full project brief and [docs/ccao-lessons.md](docs/ccao-lessons.md) for
the design patterns borrowed from the Cook County Assessor's open-source stack.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# Smoke-test the snapshot pipeline with a small fetch
uv run philly snapshot carto opa_properties_public --limit 1000

# The full pipeline: raw snapshots -> staged tables -> sale-validity mart
uv run philly snapshot-all      # capture all core tables (or: philly snapshot carto <table>)
uv run philly stage             # typed/deduped/classified staged tables (polars)
uv run philly validate-sales    # marts/sale_validity.parquet with reason codes
uv run philly build-features    # marts/sale_features.parquet (registry: docs/features.md)
uv run philly freshness         # heartbeat: exit 1 if snapshots are missing/stale

# See what's on disk, then query it (views: raw_<dataset>, stg_<table>, mart_<table>)
uv run philly catalog
uv run philly sql "
  SELECT a.year, a.market_value, o.total_livable_area
  FROM raw_assessments a
  JOIN raw_opa_properties_public o USING (parcel_number)
  WHERE o.location = '108 ELFRETHS ALY'
  ORDER BY a.year"
```

See [docs/operations.md](docs/operations.md) for the weekly launchd schedule.

Snapshots land under `data/raw/source=carto/dataset=<table>/fetched_at=<utc>/`
as zstd-compressed Parquet plus a `manifest.json` recording the query, schema,
row counts, timing, and file checksums. Raw data is never modified after write.

## Layout

```
src/philly_assessments/
  config.py            # data dir resolution + core snapshot table registry
  sources/carto.py     # CARTO SQL API client (schema, counts, keyset pagination)
  ingest/manifests.py  # snapshot + derived-table manifest schemas (pydantic)
  ingest/snapshots.py  # snapshot writer (pages -> Parquet + manifest)
  staging/             # raw -> typed/deduped/classified tables (polars)
  validation/sales.py  # CCAO-style sale-validity classification
  features/            # model-ready feature marts (see docs/features.md)
  catalog.py           # DuckDB views over raw snapshots + staged/mart tables
  cli.py               # `philly` command-line entry point
docs/
  source_inventory.md  # verified dataset inventory (Milestone 1)
  ccao-lessons.md      # patterns adopted from ccao-data
  operations.md        # recurring snapshot schedule + freshness heartbeat
data/                  # local data lake (gitignored): raw/ staged/ marts/
```

## Tech stack

Modern, minimal, and pandas-free by policy:

| Layer | Choice | Notes |
|---|---|---|
| Package/env manager | **uv** (+ `uv_build` backend) | Python 3.13 pinned via `.python-version` |
| HTTP | **httpx** (+ **tenacity** retries) | mocked in tests with **respx** |
| Columnar data | **pyarrow** → zstd **Parquet** | ingest streams API pages straight to Arrow |
| Analytical SQL | **DuckDB** | query engine over raw Parquet snapshots |
| DataFrames | **Polars** (not pandas) | enters with the staging/feature layer; ingest and verification need only Arrow + SQL |
| Validation/config | **pydantic v2** | snapshot manifests |
| Lint/test | **ruff**, **pytest** | offline-by-default test suite |

Planned additions as milestones land: `dbt-duckdb` (staged/mart models),
`assesspy` (IAAO ratio statistics), LightGBM (baseline model), PyMC (Bayesian
hierarchical model), DVC (modeling pipeline versioning). pandas and requests
are deliberately excluded; if a dependency drags pandas in transitively, it
stays out of our code paths.

## Tests

```bash
uv run pytest            # offline tests (HTTP mocked)
uv run pytest -m live    # live smoke tests against the real CARTO API
```
