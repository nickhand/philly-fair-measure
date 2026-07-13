# Operations: recurring snapshots

Snapshotting is a core feature, the time series only accrues value once
captures happen on a schedule, and a scheduler that silently dies is worse
than none. Two commands cover this:

```bash
uv run fair-measure snapshot-all   # capture all core tables (continues past failures, exits 1 if any failed)
uv run fair-measure freshness      # heartbeat: exits 1 if any core dataset is missing or > 8 days old
```

The core table set lives in `philly_fair_measure.config.CORE_CARTO_TABLES`.
Parcel polygons (`fair-measure snapshot arcgis PWD_PARCELS`, ~10 min) change rarely;
refresh them occasionally rather than weekly, then re-run
`fair-measure stage --tables parcels`.
Building footprints are also a separate large ArcGIS capture. Refresh and
stage the current-only record-consistency layer with:

```bash
uv run fair-measure snapshot arcgis LI_BUILDING_FOOTPRINTS --dataset building_footprints
uv run fair-measure stage --tables building_footprints
```

A default `fair-measure stage` skips this optional table when no footprint
snapshot exists; an explicit request remains strict.
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

After a fresh capture, rebuild derived layers:

```bash
uv run fair-measure stage
uv run fair-measure validate-sales
```

## Full model refresh (coherence chain)

Relearning market areas relabels geography, and any mart rebuild can shift
training rows, so models must retrain before re-screening (the screen warns
when a run predates its mart). The full order:

```bash
uv run fair-measure stage
uv run fair-measure validate-sales
uv run fair-measure build-market-areas   # optional; relabels geography, forces retrains
uv run fair-measure build-price-index
uv run fair-measure build-proximity      # after refreshing SEPTA/parks/centerline snapshots
uv run fair-measure build-features
uv run fair-measure build-condo-features
uv run fair-measure train-baseline
uv run fair-measure train-baseline --market retail   # financed-only retail-value model
uv run fair-measure train-bayesian       # ~5-10 min (nutpie)
uv run fair-measure train-condo
uv run fair-measure screen-assessments   # residential (Bayesian PI) + condo (conformal) rows
uv run fair-measure conformal-check      # frequentist cross-check of the screen intervals
```

`fair-measure acs-sensitivity` is an on-demand diagnostic (never a production
model); rerun it after major feature changes to keep the measured cost of the
demographics ban current.

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
