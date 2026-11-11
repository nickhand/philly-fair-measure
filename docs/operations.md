# Operations: snapshots, rebuilds and deploys

Snapshotting is a core feature, the time series only accrues value once
captures happen on a schedule, and a scheduler that silently dies is worse
than none. Two commands cover this:

```bash
uv run fair-measure snapshot-all   # capture the active core tables (continues past failures, exits 1 if any failed)
uv run fair-measure freshness      # heartbeat: exits 1 if any core dataset is missing or > 8 days old
```

The core table set lives in `philly_fair_measure.config.CORE_CARTO_TABLES`.
`snapshot-all` skips the tables in `PAUSED_CARTO_TABLES` and prints why. Today
that is the retired `real_estate_tax_delinquencies` table, which CARTO denies
(see [the snapshot program](snapshots/README.md)). Name a paused table in
`snapshot-all --tables` to check whether access is back.

A full rebuild also reads ArcGIS layers: parcel polygons, building footprints,
the SEPTA, park, street-centerline and bike-network layers that
`build-proximity` reads, and the ACS tract demographics that
`export-web-stats` reads. `just snapshot-sources` captures `snapshot-all` and
every one of those layers; `just --dry-run snapshot-sources` prints the
commands. The layers change rarely, so refresh them occasionally rather than
weekly (parcel polygons take about 10 minutes). After a refresh, run
`just retrain-all` (below). Restaging one table leaves the marts built from
the old layer.

A default `fair-measure stage` skips building footprints and delinquencies
when they have no snapshot. An explicit `stage --tables` request remains
strict.
A full weekly capture is currently ~842MB of zstd Parquet (~44GB/year).
Per the project brief, do not prematurely optimize away full snapshots;
revisit with delta tables once change detection lands.

## Weekly schedule (launchd, macOS)

```bash
mkdir -p data/logs
cp scripts/com.philly-fair-measure.snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.philly-fair-measure.snapshot.plist

# run once immediately to verify
launchctl start com.philly-fair-measure.snapshot
tail -f data/logs/snapshot.log
```

Runs Mondays 07:00 local time; launchd fires missed runs at the next wake, so
a closed laptop on Monday morning still snapshots later that day.

## Heartbeat, silence is not success

The freshness check is the alarm for a scheduler that stopped running
(the CCAO runs a dedicated service for exactly this failure mode). Check it
manually, or wire it into anything that runs regularly, e.g. a shell profile
nag or a weekly reminder:

```bash
cd /Users/nhand/DataProjects/philly-fair-measure && uv run fair-measure freshness \
  || echo "⚠️  Philly snapshots are stale, check data/logs/snapshot.log"
```

To rebuild from a fresh capture, run `just retrain-all` (below). Rebuilding
only `stage` and `validate-sales` leaves the market areas, the price index and
the feature marts built from the older sale-validity mart.

## Full rebuild (coherence chain)

`just retrain-all` is the one rebuild sequence. The README's "Reproducing it"
section and this page name the recipe instead of copying its steps, and
`tests/test_pipeline_sequence.py` fails when a step comes before the step that
writes one of its inputs. `just --dry-run retrain-all` prints the commands:
staging, sale validity, market areas, price index, proximity, characteristic
quality, the residential and condo feature marts, every model (the Bayesian
fit takes 5 to 10 minutes), the screen, the review queue, `export-web-stats`
and `sync-docs`.

Market areas and the price index derive from the sale-validity mart, and the
feature marts read all three. Relearning market areas relabels geography, and
any mart rebuild can shift training rows, so every model retrains before the
screen is rebuilt. The screen refuses to build when a run predates the
sale-feature, market-area or price-index mart, unless `--allow-stale` is
passed.

Two diagnostics sit outside the sequence because nothing in it reads their
output. `fair-measure conformal-check` is a frequentist cross-check of the
screen intervals. `fair-measure acs-sensitivity` (never a production model)
measures the cost of the demographics ban; rerun it after major feature
changes.

## Publishing a rebuild

The site and the API show the same screen from two copies. Prerendered pages
print the counts in `web/src/data/siteStats.json`. After the home page mounts,
it replaces them with `/api/stats`, which the API computes from the screen in
its deploy bundle. Publish both after every `just rescreen` or
`just retrain-all`. If only the site ships, the home page counts change a
moment after the page loads, and property reports come from an older screen
than the published statistics.

1. Rebuild with `just retrain-all`, or with `just rescreen` when the models
   are unchanged. Both end with `export-web-stats` and `sync-docs`.
2. Commit `web/src/data/siteStats.json` and the regenerated doc blocks.
3. Run `just bundle-data`. It copies the screen, the feature marts and the
   model artifacts the API serves into `deploy/data`.
4. Run `just api-smoke`. It boots the API against that bundle in a venv that
   holds only the `serve` dependency group and calls every endpoint.
5. The owner deploys the API with `just fly-deploy`, which repeats steps 3
   and 4 before `flyctl deploy`.
6. The owner deploys the site by merging the commit from step 2 to `main`. A
   change under `web/` routes CI to its `deploy-production` job, which
   publishes the built site to Cloudflare.

## Aerial change evidence (on-demand)

```bash
uv run fair-measure aerial-score          # score the screen's flagged parcels (2023 vs 2025 flights)
uv run fair-measure screen-assessments    # rerun to embed aerial_change_score/flag columns
```

Scores come from free PASDA orthophotos (only the 2020/2023/2024/2025
services render, probe before assuming other vintages). The threshold is
recalibrated per vintage pair from a fresh quiet-control sample (90th
percentile ≈ 10% false-positive budget; catches ~42% of known structural
change per the pilot). Keep runs to the flagged set, citywide would be ~1M
requests against Penn State's free service. `fair-measure aerial-pilot` re-runs
the ground-truth validation.

## Property reports

```bash
uv run fair-measure report "108 ELFRETHS ALY"   # or a parcel id
```

Writes a self-contained printable HTML packet to `data/reports/<parcel>.html`:
assessment vs the model's 90% interval, comps, the identical-twin uniformity
exhibit (PA uniformity clause), aerial/complaint/tenure evidence, assessment
and sale history, provenance. Sections render only when evidence exists;
condo parcels get a reduced packet (no comps/twins yet).
