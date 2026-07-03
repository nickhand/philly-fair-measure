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
