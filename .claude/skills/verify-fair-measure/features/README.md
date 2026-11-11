# Fair Measure verification map

The maintained list of what a Fair Measure user touches and how to prove each part works. Read this index, then drive the feature file that matches the change. `$S` is `.claude/skills/verify-fair-measure/scripts/fm-verify`, run from the worktree root.

## Baseline preconditions

- Commands run from the root of the checkout under test. It has the `data`, `deploy` and `web/node_modules` links (`$S setup <slug>`), or exports `PHILLY_DATA_DIR` in place of the `data` link.
- The lake is the 2026-07-14 build. `marts/assessment_screen.parquet` has 496,975 rows from runs `20260714T190028Z-baseline`, `20260714T193149Z-bayesian` and `20260714T194046Z-condo`. A rebuilt lake changes the counts quoted below; re-measure them with `remeasure_screen.py` instead of trusting these.
- Seed parcels: `052174500` (108 ELFRETHS ALY, residential, within range), `591073500` (1154 E PRICE ST, residential, over-assessed), `888520502` (3600 CONSHOHOCKEN AVE #1001, condo).
- The API runs from `$S start-api <slug>`; the site is `$S build-site <slug>` then `$S start-preview <slug>`.
- `$S doctor <slug>` passes and lists every server as started by this run.
- The map loads its basemap from `tiles.openfreemap.org`, so map journeys need internet. Everything else is local.

## Driving conventions

- Start from a fresh build of the branch under test. `just gates` and `npm run build:cloudflare:*` overwrite `web/dist`; rebuild with `$S build-site` after them.
- Locate by ARIA role and accessible name, as `$S browse` does. The handles below come from the `.vue` templates and the ARIA snapshots of a real run.
- Every request goes through `$S get`, `$S page`, `$S browse`, `$S cli`, `$S remeasure` or `$S ci` so it lands in `commands.log` and the evidence folder.
- Never run a command that writes the lake (`data/`) or the deploy bundle (`deploy/data`) except into `data/verify/`.

## Proof and skip reporting

- Site proof comes from the built page, as a `$S page` HTML capture for prerendered copy or a `$S browse` screenshot plus ARIA snapshot for rendered state.
- API proof is a saved response from a running instance plus `just api-smoke` output.
- Number proof is a recount from the mart compared with every place the number appears.
- Report the evidence folder path, the slug, and which entry points of the feature file you drove.
- An entry point you could not drive is reported with the command and the unmet precondition, never as verified through another path.

## Feature entry contract

Each feature file has an H1, one paragraph on the user-visible behavior, then four H2s in this order.

1. `Sub-features` lists short IDs with one line each.
2. `How to get to it (user POV)` lists every entry point.
3. `Driving it with fm-verify` starts with `Preconditions:` and pairs each action with an exact command and the observable result.
4. `Gotchas` lists traps that waste or invalidate a run.

## Features

- [Property search and report](./property-report.md) covers the address search and the per-property report page with comps.
- [Assessment map](./flagged-map.md) covers the citywide map of flagged homes, its legend filters and the property sheet.
- [Published pages and numbers](./published-numbers.md) covers the prerendered pages and the counts and statistics they print.
- [API report and comps](./api-report-and-comps.md) covers the JSON endpoints behind the report, the map and the home counters, and the serve-only smoke test.
- [Screen numbers and lineage](./screen-numbers.md) covers the assessment screen mart, the model runs it came from, and the read-only CLI views of it.
- [CI and workflow changes](./ci-workflows.md) covers change routing, the release contract tests, the job commands, and what only a GitHub run proves.
