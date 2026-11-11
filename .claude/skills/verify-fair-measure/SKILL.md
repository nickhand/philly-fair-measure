---
name: verify-fair-measure
description: Prove a Fair Measure change on the real artifact. Covers the FastAPI API (a running `fair-measure api` driven with curl, plus `just api-smoke`), the prerendered Vue site (the built web/dist pages and a vite preview driven in headless Chrome or the desktop browser pane), and the pipeline (read-only polars recounts of data/marts and model-run manifests). Use before saying an audit fix, API change, site change, CLI change, or published number works.
---

# Verify Fair Measure

Run everything from the root of the checkout under test. The helper is

```bash
S=.claude/skills/verify-fair-measure/scripts/fm-verify
```

The helpers act on the checkout of the current directory, wherever they live: its code, its `.venv`, its `web/`, and its `data` link or `PHILLY_DATA_DIR`. A checkout that predates this skill can call them by absolute path from one that has it. `$S` with no arguments lists its commands. Each takes a `<slug>` naming the change, such as `fix-search-trim`. The slug keys the evidence folder and the processes the run owns. Use a new slug per run; a reused slug appends to its earlier folder. Pass the same `FM_*` port variables to every call of one run.

## What counts as proof

| Change | Proof |
|---|---|
| Site copy, layout, a page | The built page a visitor gets: `web/dist/<page>.html` after `$S build-site`, and the page driven in a browser against `$S start-preview`. The `.vue` source is not proof. |
| API (`api.py`, scoring, comps, the deploy bundle) | `just api-smoke`, plus requests against a running instance with `$S get`. |
| A published number | Re-measure it from the mart (`$S remeasure` or a polars query) and compare with `web/src/data/siteStats.json` and every page or endpoint that shows it. |
| CLI | `$S cli` with `--help`, plus a read-only run of the command. |
| CI or workflow | `$S ci` (contract tests, routing, YAML parse) and the changed job's commands. Scheduled runs, the production deploy job, Cloudflare publishing, Fly deploys and the S3 snapshot job cannot run locally; list them as unverified. |
| Anything, before a PR | `just gates`. It rebuilds `web/dist` with analytics on, so run `$S build-site` again before driving the preview. |

Drive the path a user takes (the search box, a URL, the request a client sends), not internal functions. Capture the action and the resulting state. Check side effects with a second view: the stored value read back, a recount from the mart.

## Setup

A worktree needs three links into the main checkout: `data` (the lake: `marts/*.parquet`, `models/run_id=*`), `deploy` (the API bundle `deploy/data`) and `web/node_modules`.

```bash
$S setup <slug>
```

creates the missing ones as absolute symlinks and warns when the main checkout's `.git/info/exclude` lacks `/data` or `/deploy` (`web/.gitignore` already ignores `node_modules`). Never `git add` them; check `git status` before each commit. Instead of the `data` link you may export `PHILLY_DATA_DIR=<main checkout>/data`; `config.data_dir()`, `$S start-api`, the doctor and remeasure all read it. `just api-smoke` still needs the `deploy` link, because `scripts/smoke_api.py` reads `deploy/data` relative to the working directory.

`uv run` builds the worktree's own `.venv` on first use (about 10 s).

The `web/node_modules` link shares more than packages. `vue-tsc --build` writes `web/node_modules/.tmp/*.tsbuildinfo`, which lands in the main checkout. Do not build in a worktree while the main checkout builds. Never run `npm ci` or `npm install` in a worktree while `web/node_modules` is a link: npm empties the link's target, which is the main checkout's install, and every linked worktree loses it at once (this happened on 2026-11-11). To give a worktree its own install, remove the link first (`rm web/node_modules`), then run `timeout 900 npm --prefix web ci`. `vite: command not found` or `Cannot find module 'playwright'` in a linked worktree means the shared install is gone; restore it from the lockfile with `timeout 900 npm --prefix <main checkout>/web ci` and say so in your report.

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

- the checkout, its lake (the `data` link or `PHILLY_DATA_DIR`; missing fails) with the screen's rows, build date and model runs, the run in `siteStats.json`, and the `deploy` and `web/node_modules` links (missing warns and names what needs them);
- for each port, the listening PID, its command and working directory, and whether this slug started it;
- for the API, `/health` and `/api/stats`, and whether their rows and build date match the data directory that process serves;
- for the site, whether `web/dist` has analytics compiled in and calls the API port in use (a hard failure only while a preview serves it), and whether the dev server's proxy reaches the API.

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

### Pipeline and CLI

Never write to the lake while verifying. Run CLI checks through

```bash
$S cli <slug> <name> <fair-measure args>
```

which runs `uv run fair-measure <args>` in the current checkout and saves `cli/<name>.txt` with the command and exit code. It allows `--help` or `-h` on any command and refuses anything else outside this table. It accepts each command's flags only when spelled in full, because argparse would read `--rep` as `--reports`. Every output path (`--out`, `--json-out`) must resolve inside the evidence folder. `sql` takes one `SELECT` or `WITH` statement with no `COPY`, `EXPORT`, `ATTACH`, `INSTALL`, `LOAD`, `CREATE`, `INSERT`, `UPDATE`, `DELETE` or `PRAGMA` in it.

| Command | Proves |
|---|---|
| `screen-audit --no-save` | screen invariants and counts |
| `catalog` | every raw, staged and mart view with rows and build time, from manifests |
| `sql "SELECT ..."` | ad hoc SQL over in-memory DuckDB views `raw_<dataset>`, `stg_<table>`, `mart_<table>` |
| `comps "108 ELFRETHS"` | one property's comps |
| `leaderboard --kind over` | the most over-assessed list (refused with `--reports`) |
| `report 052174500 --out <evidence>/reports` | the static appeal packet |
| `export-web-stats --out <evidence>/siteStats.json` | every site statistic recomputed; diff it against `web/src/data/siteStats.json`, where only `meta.generated_at` should differ |
| `sync-docs --check` | the generated README.md and docs/model.md blocks match `siteStats.json` |
| `freshness`, `snapshot-diff [--out <evidence>/<file>]` | snapshot ages and changes |
| `<any command> --help` | a changed command's arguments |

The recount of the published screen numbers:

```bash
$S remeasure <slug> --api http://127.0.0.1:8000 --html web/dist/index.html
```

runs `scripts/remeasure_screen.py`, which recounts the flags from `marts/assessment_screen.parquet` with polars and compares the manifest, `siteStats.json`, `/api/stats` and the built home page. `--api` and `--html` are optional. It saves `remeasure.json` and `remeasure.txt` and exits 1 on any difference.

`data/marts/assessment_screen.manifest.json` lists the `models/<run_id>` inputs (baseline, bayesian, condo) the screen was built from, and each `data/models/run_id=<id>/run.manifest.json` lists what that run trained on. `siteStats.json` `meta.model_run_id` and `meta.interval_run_id` must appear among the screen's inputs; remeasure checks it. For any other number, write the polars query and `tee` it into the evidence folder:

```bash
uv run python -c "import polars as pl; s = pl.scan_parquet('data/marts/assessment_screen.parquet'); print(s.group_by('model_family', 'assessment_flag').len().collect())"
```

### CI and workflows

```bash
$S ci <slug> [base, default origin/main]
```

runs the `.github/ci` contract tests, pipes every changed path (committed, staged, unstaged, untracked) through `.github/ci/scope.py` to show the `python=`, `web=`, `release=` routing CI would pick, and parses `.github/workflows/*.yml`. It saves `ci.txt`. [`features/ci-workflows.md`](features/ci-workflows.md) covers the job commands and what only a real GitHub run proves.

## Cleanup

```bash
$S stop <slug>
```

kills only the process groups this slug started (recorded under `$TMPDIR/fm-verify/<slug>/`), removes that scratch folder, reports any port still held by someone else, lists any file under the main checkout's `data/` (outside `verify/`) or `deploy/` modified since the run began into `lake-writes.txt`, and lists the evidence it kept. A lake write you did not intend means the verification itself changed the artifact; say so. Close browser pane tabs with `mcp__Claude_Browser__tabs_close`. Leave `web/dist` and `.venv-serve`; they are gitignored build output. Run stop after a failed attempt too, then confirm the evidence folder still lists its files.

## Feature map

[`features/README.md`](features/README.md) indexes the user-facing features. Drive the file that matches the change. A proof through one entry point is incomplete when the file lists others. Drive them or report them as not driven.
