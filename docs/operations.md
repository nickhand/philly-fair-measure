# Operations: recurring snapshots

Snapshotting is a core feature — the time series only accrues value once
captures happen on a schedule, and a scheduler that silently dies is worse
than none. Two commands cover this:

```bash
uv run philly snapshot-all   # capture all core tables (continues past failures, exits 1 if any failed)
uv run philly freshness      # heartbeat: exits 1 if any core dataset is missing or > 8 days old
```

The core table set lives in `philly_assessments.config.CORE_CARTO_TABLES`.
Parcel polygons (`philly snapshot arcgis PWD_PARCELS`, ~10 min) change rarely;
refresh them occasionally rather than weekly, then re-run
`philly stage --tables parcels`.
A full weekly capture is currently ~842MB of zstd Parquet (~44GB/year).
Per the project brief, do not prematurely optimize away full snapshots;
revisit with delta tables once change detection lands.

## Weekly schedule (launchd, macOS)

```bash
mkdir -p data/logs
cp scripts/com.philly-assessments.snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.philly-assessments.snapshot.plist

# run once immediately to verify
launchctl start com.philly-assessments.snapshot
tail -f data/logs/snapshot.log
```

Runs Mondays 07:00 local time; launchd fires missed runs at the next wake, so
a closed laptop on Monday morning still snapshots later that day.

## Heartbeat — silence is not success

The freshness check is the alarm for a scheduler that stopped running
(the CCAO runs a dedicated service for exactly this failure mode). Check it
manually, or wire it into anything that runs regularly, e.g. a shell profile
nag or a weekly reminder:

```bash
cd /Users/nhand/DataProjects/philly-property-assessments && uv run philly freshness \
  || echo "⚠️  Philly snapshots are stale — check data/logs/snapshot.log"
```

After a fresh capture, rebuild derived layers:

```bash
uv run philly stage
uv run philly validate-sales
```

## Full model refresh (coherence chain)

Relearning market areas relabels geography, and any mart rebuild can shift
training rows, so models must retrain before re-screening (the screen warns
when a run predates its mart). The full order:

```bash
uv run philly stage
uv run philly validate-sales
uv run philly build-market-areas   # optional; relabels geography — forces retrains
uv run philly build-price-index
uv run philly build-proximity      # after refreshing SEPTA/parks/centerline snapshots
uv run philly build-features
uv run philly build-condo-features
uv run philly train-baseline
uv run philly train-bayesian       # ~5-10 min (nutpie)
uv run philly train-condo
uv run philly screen-assessments   # residential (Bayesian PI) + condo (conformal) rows
uv run philly conformal-check      # frequentist cross-check of the screen intervals
```

`philly acs-sensitivity` is an on-demand diagnostic (never a production
model); rerun it after major feature changes to keep the measured cost of the
demographics ban current.

## Aerial change evidence (on-demand)

```bash
uv run philly aerial-score          # score the screen's flagged parcels (2023 vs 2025 flights)
uv run philly screen-assessments    # rerun to embed aerial_change_score/flag columns
```

Scores come from free PASDA orthophotos (only the 2020/2023/2024/2025
services render — probe before assuming other vintages). The threshold is
recalibrated per vintage pair from a fresh quiet-control sample (90th
percentile ≈ 10% false-positive budget; catches ~42% of known structural
change per the pilot). Keep runs to the flagged set — citywide would be ~1M
requests against Penn State's free service. `philly aerial-pilot` re-runs
the ground-truth validation.
