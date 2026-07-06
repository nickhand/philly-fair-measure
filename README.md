# Fair Measure — Philadelphia property assessment check

An independent, open-data check of Philadelphia's property assessments. The
system ingests the city's own published records, trains automated valuation
models on them, and compares the Office of Property Assessment's (OPA) value
for every residential property against a model estimate with a 90% predictive
interval. Where the city's value falls outside that interval, the property is
flagged, and the evidence — comparable sales, assessment history, peer
comparisons — is published in a per-property report.

**Live site:** [nickhand.dev/fair-measure](https://nickhand.dev/fair-measure/)
· **Model documentation:** [docs/model.md](docs/model.md)

As of the July 2026 run (Tax Year 2027 assessments), the screen covers
**496,975** residential properties and condos: **1,643** flagged as likely
over-assessed, **6,253** as likely under-assessed, and **44,408** inside the
interval but near its edge ("worth a look"). A residential flag requires two
independent uncertainty methods — the Bayesian posterior interval and a
spatially weighted conformalized-quantile-regression band — to both place the
city's value outside on the same side. 93 records with no recorded livable
area are reported as insufficient rather than valued.

## What it does

- Snapshots verified [OpenDataPhilly](https://opendataphilly.org/) datasets
  (property characteristics, assessment history, deed transfers, permits) into
  an immutable, manifest-tracked local data lake.
- Classifies sale validity (arm's-length vs. distressed/related-party/nominal)
  following the Cook County Assessor's published methodology.
- Trains valuation models on public data only: a LightGBM point model with
  financed-market calibration and conformalized-quantile-regression intervals
  (what the site displays), cross-examined by a hierarchical Bayesian model —
  a flag requires both methods to agree.
- Screens every assessment: OPA's value is compared against the model's 90%
  interval, and the disagreement is expressed in predictive-uncertainty units
  (`screen_z`), so a flag always accounts for how certain the model is about
  that specific property.
- Serves the results as a public dashboard (Vue 3 + MapLibre) backed by a
  FastAPI JSON API, with a per-property report designed around Philadelphia's
  First Level Review and formal appeal process.

## Results

Out-of-time test set (n = 19,484), run `20260706T222312Z-baseline`. The same
homes, the same treatment; OPA's assessed values are the incumbent benchmark.

On the IAAO ratio-study basis (financed, arm's-length sales — the standard
assessment offices are evaluated on):

| | Median ratio | COD | PRD | PRB | MAPE |
|---|---|---|---|---|---|
| This model | 1.001 | 19.3 | 1.024 | +0.010 | 19.3% |
| OPA | 0.848 | 24.7 | 1.070 | −0.058 | 24.9% |

On the full untrimmed sample, including cash and distressed sales:

| | Median ratio | COD | PRD | PRB | MAPE |
|---|---|---|---|---|---|
| This model | 1.031 | 25.5 | 1.087 | −0.073 | 26.4% |
| OPA | 0.983 | 34.5 | 1.190 | −0.234 | 34.0% |

IAAO targets for reference: median ratio 0.90–1.10, COD ≤ 15 (single-family),
PRD 0.98–1.03, |PRB| ≤ 0.05. The model meets the median-ratio and PRD/PRB
bands on the IAAO basis; neither the model nor OPA meets the COD target on the
full sample, which includes the cash/distressed tail. PRD above 1 and PRB
below 0 indicate regressivity — cheaper homes over-assessed relative to
expensive ones — and the persistent finding is that the model is substantially
less regressive than OPA on identical data.

Full methodology, caveats (including interval undercoverage in the cheapest
quintile and condo parity with OPA), and stability checks are in
[docs/model.md](docs/model.md) and the
[vertical-equity report card](docs/vertical-equity-report-card.md).

## How it works

```
snapshot (CARTO → Parquet + manifest)
  → stage (typed / deduped / classified, polars)
  → sale validity (CCAO-style reason codes)
  → feature marts (sales + assessment-date frames; docs/features.md)
  → models (LightGBM point + calibration; Bayesian / conformal intervals)
  → assessment screen (flag + screen_z + attention tier per parcel)
  → API + dashboard (FastAPI; Vue 3)
```

Three rules shape the modeling (details in [docs/model.md](docs/model.md)):

1. **Independence from OPA.** No assessment field is a model input; OPA's
   values enter only as the benchmark on the test set.
2. **No demographic features.** Race, income, and similar variables are never
   valuation inputs; they are used only in after-the-fact equity diagnostics.
3. **Strict out-of-time evaluation.** Models are trained on earlier sales and
   evaluated on later ones, matching how an assessment is actually used.

## Reproducing it

Requires [uv](https://docs.astral.sh/uv/) (Python 3.13) and Node 20+ for the
dashboard. All data comes from public APIs; no credentials are needed.

```bash
uv sync

# Data pipeline: raw snapshots → staged tables → sale-validity mart
uv run fair-measure snapshot-all      # capture all core tables
uv run fair-measure stage             # typed/deduped/classified staged tables
uv run fair-measure validate-sales    # marts/sale_validity.parquet with reason codes

# Features and models
uv run fair-measure build-features        # residential feature marts
uv run fair-measure build-condo-features  # condo feature marts
uv run fair-measure train-baseline        # LightGBM + Ridge, benchmarked against OPA
uv run fair-measure train-baseline --market retail   # financed-only variant
uv run fair-measure train-bayesian        # hierarchical Bayesian intervals
uv run fair-measure train-condo           # condo LightGBM + conformal intervals

# The screen and the site's statistics
uv run fair-measure screen-assessments   # flag OPA values outside each interval
uv run fair-measure export-web-stats     # regenerate web/src/data/siteStats.json

# The public dashboard: API + Vue app
uv run fair-measure api                  # JSON API on :8000
npm --prefix web install && npm --prefix web run dev   # site on :5173

# Inspect what's on disk (DuckDB views: raw_<dataset>, stg_<table>, mart_<table>)
uv run fair-measure catalog
uv run fair-measure sql "SELECT ... FROM mart_assessment_screen LIMIT 5"
```

A `Justfile` wraps the common sequences (`just retrain-all`, `just gates`,
`just fly-deploy`); run `just` to list recipes. `fm` is a shorthand alias for
the `fair-measure` command. Snapshots land under
`data/raw/source=carto/dataset=<table>/fetched_at=<utc>/` as zstd-compressed
Parquet plus a `manifest.json` recording the query, schema, row counts, and
file checksums; raw data is never modified after write. The screen refuses to
run against mismatched model runs (a coherence gate compares run manifests)
rather than silently mixing generations.

## Repository layout

```
src/philly_fair_measure/
  config.py            # data dir resolution + core snapshot table registry
  sources/carto.py     # CARTO SQL API client (schema, counts, keyset pagination)
  ingest/              # snapshot writer + manifest schemas (pydantic)
  staging/             # raw → typed/deduped/classified tables (polars)
  validation/sales.py  # CCAO-style sale-validity classification
  validation/opa.py    # assessment screen: flags, screen_z, attention tier
  features/            # model-ready feature marts (registry: docs/features.md)
  models/              # LightGBM/Bayesian/conformal models, scoring, IAAO metrics
  equity_context.py    # peer-group definitions shared by stats and reports
  web_stats.py         # exports the site's committed statistics JSON
  catalog.py           # DuckDB views over raw snapshots + staged/mart tables
  api.py               # FastAPI app backing the public dashboard
  cli.py               # `fair-measure` / `fm` command-line entry point
web/                   # public dashboard: Vue 3 + TypeScript + Tailwind + MapLibre
scripts/               # deploy-bundle builder + serve-only API smoke test
docs/                  # documentation (see below)
data/                  # local data lake (gitignored): raw/ staged/ marts/ runs/
```

## Documentation

| Document | Contents |
|---|---|
| [docs/model.md](docs/model.md) | Model architecture, methodology, results — the site's "model documentation" link |
| [docs/features.md](docs/features.md) | Input feature registry |
| [docs/source_inventory.md](docs/source_inventory.md) | Verified public dataset inventory |
| [docs/vertical-equity-report-card.md](docs/vertical-equity-report-card.md) | Model vs. OPA vs. IAAO bands, full and trimmed samples |
| [docs/report-assessment-equity.md](docs/report-assessment-equity.md) | Equity findings: who is over- and under-assessed |
| [docs/equity-diagnostics.md](docs/equity-diagnostics.md) | Diagnostic methodology (demographics excluded from valuation) |
| [docs/historical-redistribution.md](docs/historical-redistribution.md) | What OPA's regressivity shifted 2016–2025, in dollars |
| [docs/ccao-lessons.md](docs/ccao-lessons.md) | Patterns adopted from the Cook County Assessor's open-source stack |
| [docs/frontend.md](docs/frontend.md) | Dashboard + API architecture and deployment |
| [docs/operations.md](docs/operations.md) | Recurring snapshot schedule + freshness checks |
| [docs/research-notes.md](docs/research-notes.md) | Literature and design notes behind the choices |

## Development

```bash
just gates    # ruff + mypy (strict) + pytest, then web tests + production build
uv run pytest             # offline tests (HTTP mocked)
uv run pytest -m live     # live smoke tests against the real CARTO API
npm --prefix web run test:unit
```

CI runs lint, strict type checks, and the offline test suite on every push and
pull request. Contribution guidelines, including the project's dependency
policies, are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Limitations

- Model estimates are statistical, not appraisals. A flag means the city's
  value is outside what public data supports — it is a reason to check the
  record, not proof of an error.
- Cash-market price dispersion is partly irreducible from public data; the
  full-sample COD reflects that.
- Predictive intervals undercover in the cheapest quintile (~76–79% realized
  vs. 90% nominal); the site reports interval-based results with that caveat.
- Condo accuracy: the model beats OPA on error (rmse 0.252 vs 0.278) and
  sits within half a COD point of OPA's uniformity (19.3 vs 18.8) — condos
  remain OPA's best segment.
- OPA's interior-condition fields are stale and cannot be independently
  verified; the model routes around them with distress and permit signals.
- Single metro; no cross-city validation.

## License

[MIT](LICENSE). The underlying records belong to their publishers and are
redistributed under the City of Philadelphia's open data terms; this
repository contains code and documentation only, never the data itself.

## Acknowledgments

The data discipline and sale-validity methodology draw heavily on the
[Cook County Assessor's Office open-source stack](https://github.com/ccao-data)
(see [docs/ccao-lessons.md](docs/ccao-lessons.md)). Data comes from
[OpenDataPhilly](https://opendataphilly.org/) and the City of Philadelphia's
CARTO API. IAAO ratio statistics are computed with
[assesspy](https://github.com/ccao-data/assesspy).
