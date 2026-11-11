---
name: verify-fair-measure
description: Prove a Fair Measure change on the real artifact. Covers the FastAPI API (a running `fair-measure api` driven with curl, plus `just api-smoke`), the prerendered Vue site (the built web/dist pages and a vite preview driven in headless Chrome or the desktop browser pane), and the pipeline (read-only polars recounts of data/marts and model-run manifests). Use before saying an audit fix, API change, site change, CLI change, or published number works.
---

# Verify Fair Measure

Run everything from the worktree root. The helper is

```bash
S=.claude/skills/verify-fair-measure/scripts/fm-verify
```

`$S` with no arguments lists its commands. Each takes a `<slug>` naming the change, such as `fix-search-trim`. The slug keys the evidence folder and the processes the run owns. Use a new slug per run; a reused slug appends to its earlier folder. Pass the same `FM_*` port variables to every call of one run.

## What counts as proof

| Change | Proof |
|---|---|
| Site copy, layout, a page | The built page a visitor gets: `web/dist/<page>.html` after `$S build-site`, and the page driven in a browser against `$S start-preview`. The `.vue` source is not proof. |
| API (`api.py`, scoring, comps, the deploy bundle) | `just api-smoke`, plus requests against a running instance with `$S get`. |
| A published number | Re-measure it from the mart (`remeasure_screen.py` or a polars query) and compare with `web/src/data/siteStats.json` and every page or endpoint that shows it. |
| CLI | `uv run fair-measure <cmd> --help`, plus a read-only run whose output goes to the evidence folder. |
| CI or workflow | The contract tests and a routing dry run (see Pipeline and CI). Scheduled runs, the production deploy job, Cloudflare publishing, Fly deploys and the S3 snapshot job cannot run locally; list them as unverified. |
| Anything, before a PR | `just gates`. It rebuilds `web/dist` with analytics on, so run `$S build-site` again before driving the preview. |

Drive the path a user takes (the search box, a URL, the request a client sends), not internal functions. Capture the action and the resulting state. Check side effects with a second view: the stored value read back, a recount from the mart.

## Setup

A worktree needs three links into the main checkout: `data` (the lake: `marts/*.parquet`, `models/run_id=*`), `deploy` (the API bundle `deploy/data`) and `web/node_modules`.

```bash
$S setup <slug>
```

creates the missing ones as absolute symlinks and warns when the main checkout's `.git/info/exclude` lacks `/data` or `/deploy` (`web/.gitignore` already ignores `node_modules`). Never `git add` them; check `git status` before each commit. Instead of the `data` link you may export `PHILLY_DATA_DIR=<main checkout>/data`, which `config.data_dir()` reads, and pass it to `$S start-api` as `FM_DATA_DIR`. `just api-smoke` still needs the `deploy` link, because `scripts/smoke_api.py` reads `deploy/data` relative to the working directory.

`uv run` builds the worktree's own `.venv` on first use (about 10 s).

The `web/node_modules` link shares more than packages. `vue-tsc --build` writes `web/node_modules/.tmp/*.tsbuildinfo`, which lands in the main checkout. Do not build in a worktree while the main checkout builds. For a fully separate tree, replace the link with `npm --prefix web ci`.

## Evidence

`$S evidence <slug>` creates and prints `<main checkout>/data/verify/<YYYY-MM-DD>-<slug>/`. The main checkout's `data/` is gitignored and reached by every worktree, so the folder survives worktree removal and is never committed. It is the only place under `data/` a verification writes.

- `meta.txt` records the branch, HEAD and dirty-file count when the folder was made.
- `commands.log` records every helper call with its status.
- `doctor.txt` collects each doctor run.
- `logs/` holds the api, preview, dev and build logs.
- `api/` holds `$S get` bodies and headers.
- `site/` holds `$S page` HTML and `$S browse` screenshots, ARIA snapshots and logs.

Save anything else you capture (CLI output, recounts) into the same folder with `tee`.

## Launch

```bash
$S start-api <slug>       # uv run fair-measure api --port 8000 --data-dir <lake>; ready in about 3 s
$S build-site <slug>      # npm --prefix web run build, VITE_ANALYTICS_ENABLED=false VITE_API_BASE=http://127.0.0.1:8000
$S start-preview <slug>   # npm --prefix web run preview on 4173, serving web/dist
$S start-dev <slug>       # vite dev on 5173 (proxies /api to 8000); never proof of the built page
```

Ready means `/health` answers for the API and `/` answers 200 for the site. Each start refuses a busy port and names its owner. Never kill a process this run did not start. Choose a free port and pass it to every later call, build-site included: `FM_API_PORT=8010 $S start-api <slug>`, then `FM_API_PORT=8010 $S build-site <slug>`. `FM_PREVIEW_PORT` and `FM_DEV_PORT` work the same way.

Use build-site, not `npm run build`. A plain build compiles PostHog analytics in, so every preview page view becomes a real analytics event. It also calls same-origin `/api`, which `npm run preview` answers with the SPA shell, because the preview fallback in `web/vite.config.ts` runs before the proxy. build-site calls the API cross-origin, as the Cloudflare build does with `https://fair-measure-api.fly.dev`; the API allows any origin by default.

Avoid `just dev`, which runs `kill -9` on whatever holds 8000 and 5173, and `just bundle-data`, which deletes and rewrites the shared `deploy/data`. The `.claude/launch.json` entries (`api`, `web`, `web-prod`) start servers that the desktop app owns, and `web-prod` serves whatever `web/dist` holds. Start servers with `$S` so cleanup knows their process groups.

## Doctor

```bash
$S doctor <slug>
```

Read-only. It appends to `doctor.txt` and exits 1 on a hard failure. It reports:

- the worktree's links, the lake's screen (rows, build date, model runs) and the run in `siteStats.json`;
- for each port, the listening PID, its command and working directory, and whether this slug started it;
- for the API, `/health` and `/api/stats`, and whether their rows and build date match the data directory that process serves;
- for the site, whether `web/dist` has analytics compiled in and which API base it calls.

Run it after launch and whenever a result looks wrong.

## Drive

### API

```bash
$S get <slug> <name> <path> [expected status, default 200]
```

saves `api/<name>.json` and `api/<name>.headers` and exits 1 on any other status. Assert on the saved file with `python3 -c` or `jq`. Routes, from `src/philly_fair_measure/api.py`:

| Path | Returns |
|---|---|
| `/health` | `status`, `rows` (screen rows), `screen_built` (screen manifest date) |
| `/api/stats` | `properties`, `within`, `over`, `under`, `watch`, `median_ratio`, `screen_built` |
| `/api/search?q=ELFRETHS` | up to 10 `{parcel_id, address, opa_market_value}`, prefix matches first |
| `/api/property/052174500` | the screen row for 108 ELFRETHS ALY; 404 for an unknown id |
| `/api/property/052174500/report` | `drivers`, `equity`, `assessment_history`, `sale_history`, `screen_built` |
| `/api/property/052174500/comps` | 8 residential comps in about 1 s; condo `888520502` gets same-building sales |
| `/api/parcels?minx=-75.17&miny=39.94&maxx=-75.14&maxy=39.96` | GeoJSON points in a viewport |
| `/api/parcels/flagged` | GeoJSON of every flagged or watch-tier home, about 10 MB uncompressed |
| `/api/admin/leaderboard?kind=over` | open locally; 404 under `PHILLY_ENV=prod` with no `PHILLY_ADMIN_TOKEN` |
| `/api/docs` | the OpenAPI UI |

Serve-only check:

```bash
just api-smoke 2>&1 | tee "$($S evidence <slug>)/logs/api-smoke.log"
```

It rebuilds the worktree's `.venv-serve` from the `serve` and `serve-smoke` groups, installs the worktree's package, and runs `scripts/smoke_api.py`, which calls every endpoint in-process against `deploy/data` with `PHILLY_ENV=prod`. It catches training-only imports on the serve path and files missing from the bundle. It opens no port and takes about 12 s with a warm uv cache. The bundle is the main checkout's `deploy/data`; if your change alters what the API reads, that bundle is stale until `just bundle-data` rewrites it, which needs the owner's go-ahead.

### Site

Prerendered pages: `web/dist/index.html`, `findings.html`, `methodology.html`, `trust.html`, `appeal.html`, `reports/ty-2027.html` and its alias `report.html`. `/map`, `/property/<id>` and `/leaderboards` have no HTML of their own; the browser renders them from `spa.html`. build-site already ran `web/scripts/check-prerender-output.mjs` (its last line is in `logs/site-build.log`). Prove copy on the served page:

```bash
$S page <slug> findings /findings
grep -c 'Philadelphia has two housing markets.' "$($S evidence <slug>)/site/findings.html"
```

Rendered state and interaction go through `$S browse`. It drives headless system Chrome (Playwright from `web/node_modules` with `channel: 'chrome'`, no download) against the preview, then saves a full-page screenshot, an ARIA snapshot, and every `/api/` response the page made.

```bash
$S browse <slug> <name> <path> [step ...]
```

Steps locate by ARIA role and accessible name (substring match): `fill:<role>:<name>=<text>`, `click:<role>:<name>`, `wait:<role>:<name>`, `text:<text>`, `gone:<text>`, `snap:<label>`. It exits 1 when a step fails and saves that state as `<name>-failed.png`. `FM_PREVIEW_PORT=5173` points it at the dev server. The feature files hold the journeys.

When the person wants to watch, or to explore before scripting a journey, use the desktop app's browser pane. `mcp__Claude_Browser__preview_start` with `url: "http://127.0.0.1:4173/"` opens a tab on the server `$S` started. Then use `find`, `computer` (`left_click` on a `ref`, `type`), `get_page_text`, `read_page` and `read_network_requests`, and close the tab with `tabs_close` in cleanup. The pane saves nothing, so rerun the journey with `$S browse` for evidence. A subagent's pane is usually hidden, and a hidden pane can stall timers and the map. Read it with `get_page_text` and recheck before concluding anything.

Cloudflare checks:

- Local, no network: `npm --prefix web run test:worker` (routing in `web/worker/index.mjs`), `npm --prefix web run test:unit -- --run`, and `npm --prefix web run build:cloudflare:staging`, which builds with base `/fair-measure/` and the Fly API, then runs `check-cloudflare-output.mjs staging` against `wrangler.jsonc`. That build replaces `web/dist`; run `$S build-site` again afterward.
- Against the live site, read-only: `node web/scripts/check-cloudflare-browser.mjs https://www.nickhand.dev/fair-measure` and `node web/scripts/check-cloudflare-release.mjs --app-base-url <url> --expected-index-sha256 <sha>` (CI runs it after a deploy). They prove what is deployed, not your branch. The browser check needs Playwright's own Chromium build, which this machine lacks; `(cd web && npx playwright install chromium)` is a download, so ask first.
- Not runnable here: `dry-run:cloudflare:*` and `deploy:cloudflare:staging` call wrangler. The production deploy runs only in the protected GitHub environment.

### Pipeline and CI

Never write to the lake while verifying. These are read-only, or write only where `--out` points:

| Command | Proves |
|---|---|
| `uv run python .claude/skills/verify-fair-measure/scripts/remeasure_screen.py --api http://127.0.0.1:8000 --html web/dist/index.html --out <evidence>/remeasure.json` | recounts the screen flags from `marts/assessment_screen.parquet` and compares the manifest, `siteStats.json`, `/api/stats` and the built home page; `--api` and `--html` are optional |
| `uv run fair-measure screen-audit --no-save` | screen invariants and counts |
| `uv run fair-measure catalog` | every raw, staged and mart view with rows and build time, from manifests |
| `uv run fair-measure sql "SELECT ..."` | ad hoc SQL over in-memory DuckDB views `raw_<dataset>`, `stg_<table>`, `mart_<table>` |
| `uv run fair-measure comps "108 ELFRETHS"` | one property's comps |
| `uv run fair-measure report 052174500 --out <evidence>/reports` | the static appeal packet |
| `uv run fair-measure export-web-stats --out <evidence>/siteStats.json` | every site statistic recomputed; diff it against `web/src/data/siteStats.json`, where only `meta.generated_at` should differ |
| `uv run fair-measure sync-docs --check` | the generated README.md and docs/model.md blocks match `siteStats.json` |
| `uv run fair-measure <cmd> --help` | a changed command's arguments |

Commands that write the lake (`snapshot*`, `stage`, `validate-sales`, `build-*`, `train-*`, `screen-assessments`, `review-queue`, `aerial-*`, `leaderboard --reports`, `report` and `screen-audit` without their flags above) are pipeline runs, not checks.

`data/marts/assessment_screen.manifest.json` lists the `models/<run_id>` inputs (baseline, bayesian, condo) the screen was built from, and each `data/models/run_id=<id>/run.manifest.json` lists what that run trained on. `siteStats.json` `meta.model_run_id` and `meta.interval_run_id` must appear among the screen's inputs; `remeasure_screen.py` checks it.

A polars recount for any other number:

```bash
uv run python -c "import polars as pl; s = pl.scan_parquet('data/marts/assessment_screen.parquet'); print(s.group_by('model_family', 'assessment_flag').len().collect())"
```

CI and workflow changes:

```bash
python3 -m unittest discover .github/ci -p 'test_*.py'        # release contracts and path routing
git diff --name-only origin/main...HEAD | python3 .github/ci/scope.py   # python=, web=, release= for this branch's commits
uv run python -c "import sys, yaml; [yaml.safe_load(open(f)) for f in sys.argv[1:]]; print('yaml ok')" .github/workflows/*.yml
```

An empty diff (nothing committed yet) makes `scope.py` answer true for all three, so commit first or pipe the paths by hand. The YAML load only proves the files parse. actionlint is not installed, and GitHub expressions, `needs` wiring, environments and secrets are checked only by a real GitHub run.

## Cleanup

```bash
$S stop <slug>
```

kills only the process groups this slug started (recorded under `$TMPDIR/fm-verify/<slug>/`), removes that scratch folder, reports any port still held by someone else, lists any file under the main checkout's `data/` (outside `verify/`) or `deploy/` modified since the run began into `lake-writes.txt`, and lists the evidence it kept. A lake write you did not intend means the verification itself changed the artifact; say so. Close browser pane tabs with `mcp__Claude_Browser__tabs_close`. Leave `web/dist` and `.venv-serve`; they are gitignored build output. Run stop after a failed attempt too, then confirm the evidence folder still lists its files.

## Feature map

[`features/README.md`](features/README.md) indexes the user-facing features. Drive the file that matches the change. A proof through one entry point is incomplete when the file lists others. Drive them or report them as not driven.
