# Screen numbers and lineage

The assessment screen (`data/marts/assessment_screen.parquet`, built by `fair-measure screen-assessments`) holds one row per residential property and condo: OPA's value, the model's estimate and 90% range, the flag (`over_assessed_candidate`, `under_assessed_candidate`, `within_range`, `insufficient_record`, `no_assessment`), and the attention tier. Every published count derives from it, and its manifest names the model runs it was built from. Pipeline users reach it through the `fair-measure` CLI.

## Sub-features

- `screen-counts` gives rows, flags by `model_family`, and the watch tier (`attention` not null).
- `screen-lineage` records `built_at`, `row_count` and input runs in `assessment_screen.manifest.json`; each `data/models/run_id=<id>/run.manifest.json` records its own inputs.
- `screen-invariants` holds no disputed flags, no median outside its display range, no estimate pinned to a range edge, no attention tier contradicting the range (`fair-measure screen-audit`).
- `screen-published` matches `web/src/data/siteStats.json` (`screen` block, `meta.model_run_id`, `meta.interval_run_id`).
- `cli-read` exposes it read-only through `catalog`, `sql`, `comps`, `leaderboard`, `report --out` and `screen-audit --no-save`.

## How to get to it (user POV)

- A pipeline maintainer runs `uv run fair-measure <command>` from the repository root (`fm` is an alias).
- An analyst queries the DuckDB views with `uv run fair-measure sql "..."`.
- A site visitor sees the counts on Home, the report and the map (see the other feature files).

## Driving it with fm-verify

Preconditions:

- The worktree's `data` link resolves (`$S doctor <slug>` passes the checkout section).
- No pipeline command is running against the lake.

- **Recount.** Run `uv run python .claude/skills/verify-fair-measure/scripts/remeasure_screen.py --out "$($S evidence <slug>)/remeasure.json"`. Exit 0 and `remeasure: OK`; on the 2026-07-14 lake, 496,975 properties, 970 over, 6,465 under, 40,200 watch, 19,020 insufficient, and both siteStats run ids found among the screen inputs.
- **Ad hoc recount.** For a number the script does not cover, write the query: `uv run python -c "import polars as pl; s = pl.scan_parquet('data/marts/assessment_screen.parquet'); print(s.group_by('model_family', 'assessment_flag').len().sort('model_family', 'assessment_flag').collect())" | tee "$($S evidence <slug>)/recount.txt"`.
- **Lineage.** Run `python3 -c "import json; m = json.load(open('data/marts/assessment_screen.manifest.json')); print(m['built_at'], m['row_count']); [print(i['dataset'], i['fetched_at']) for i in m['inputs']]"`. The `models/...` inputs are the runs the screen used; `cat data/models/run_id=<id>/run.manifest.json` shows what each run trained on.
- **Invariants.** Run `uv run fair-measure screen-audit --no-save | tee "$($S evidence <slug>)/screen-audit.txt"`. Exit 0 with `invariants: OK`.
- **Catalog.** Run `uv run fair-measure catalog | tee "$($S evidence <slug>)/catalog.txt"`. `mart_assessment_screen` shows 496,975 rows built `20260714T194235Z`.
- **CLI surface.** For a changed command run `uv run fair-measure <command> --help`, then a read-only invocation that writes only to the evidence folder, such as `uv run fair-measure comps "108 ELFRETHS" --k 5` or `uv run fair-measure report 052174500 --out "$($S evidence <slug>)/reports"`.

## Gotchas

- `screen-audit` without `--no-save` overwrites `marts/assessment_screen_audit.json`, and its "deltas vs previous audit" compare against that file.
- `report` and `leaderboard --reports` write `data/reports/` unless given `--out`.
- `export-web-stats` recomputes much more than the screen block (accuracy cards, tiers, redistribution) and needs the baseline run's `predictions.parquet`; use `--out` into the evidence folder.
- Polars `drop_nulls` keeps float NaN. Use `is_finite()` or `fill_nan(None)` when recounting price columns.
- Pipeline commands that write (`stage`, `validate-sales`, `build-*`, `train-*`, `screen-assessments`, `review-queue`, `snapshot*`, `aerial-*`) are runs, not checks. The screen refuses stale model runs unless `--allow-stale`, so a partial rebuild leaves the lake incoherent. Never run them to verify.
