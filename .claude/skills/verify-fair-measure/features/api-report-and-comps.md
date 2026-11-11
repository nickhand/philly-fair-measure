# API report and comps

The JSON API (`src/philly_fair_measure/api.py`, served by `fair-measure api` locally and by the Fly.io image in production) backs the site: address search, one property's screen row, its report evidence, its comparable sales, the map payloads, the home counters, and a staff-only leaderboard that production hides.

## Sub-features

- `api-health` answers `/health` with `status`, `rows` and `screen_built` (Fly health check).
- `api-stats` answers `/api/stats` with the screen counts the home page shows.
- `api-search` returns up to 10 address matches, prefix matches first; rejects `q` under 2 or over 80 characters with 422.
- `api-property` returns one screen row; 404 for an unknown parcel.
- `api-report` returns `drivers`, `equity`, `assessment_history`, `sale_history`, `screen_built`.
- `api-comps` returns 8 leaf-similarity comps for a residential parcel, same-building sales for a condo; 503 if model artifacts are missing.
- `api-admin` serves `/api/admin/leaderboard` locally, 403 with a wrong `X-Admin-Token`, 404 under `PHILLY_ENV=prod` with no token configured.
- `api-bundle` serves the business endpoints from the trimmed `deploy/data` bundle with only the `serve` dependency group installed.

## How to get to it (user POV)

- The site calls it: Home (`/api/stats`, `/api/search`), the property report (`/api/property/<id>`, `/report`, `/comps`), the map (`/api/parcels/flagged`, `/api/parcels`).
- Anyone can call it directly: `https://fair-measure-api.fly.dev` in production, `http://127.0.0.1:8000` locally, with an OpenAPI UI at `/api/docs`.

## Driving it with fm-verify

Preconditions:

- `$S start-api <slug>` is ready and `$S doctor <slug>` reports `serves <lake>` with matching rows and build date.

- **Search.** Run `$S get <slug> search-elfreths '/api/search?q=ELFRETHS'`. 200; the first hit is `{"parcel_id": "052174500", "address": "108 ELFRETHS ALY", ...}` and there are 10 hits. Run `$S get <slug> search-short '/api/search?q=E' 422` for the length guard.
- **Property.** Run `$S get <slug> property-052174500 /api/property/052174500` (200, `model_family` `residential`, `opa_market_value` 441900.0) and `$S get <slug> property-missing /api/property/000000000 404`.
- **Report.** Run `$S get <slug> report-052174500 /api/property/052174500/report`. 200; `drivers` is not null, `assessment_history` and `sale_history` are non-empty, `screen_built` equals `/health`'s.
- **Comps.** Run `$S get <slug> comps-052174500 /api/property/052174500/comps` (8 rows with `address`, `sale_date`, `sale_price`, `price_adj_today`, `livable_area`, `distance_m`, `similarity`) and `$S get <slug> comps-condo /api/property/888520502/comps` (rows with `distance_m` 0).
- **Assert.** `python3 -c "import json,sys; r=json.load(open(sys.argv[1])); assert r['drivers'] and r['assessment_history'], r; print('report ok')" "$($S evidence <slug>)/api/report-052174500.json"`; repeat the pattern per response.
- **Admin lock.** Locally `$S get <slug> admin-local '/api/admin/leaderboard?kind=over&n=5'` is 200. The prod posture (404) is asserted by `just api-smoke`.
- **Serve-only bundle.** Run `just api-smoke 2>&1 | tee "$($S evidence <slug>)/logs/api-smoke.log"`. It ends with `smoke test passed — the bundle serves every endpoint`.

## Gotchas

- `just api-smoke` runs the worktree's code against the main checkout's `deploy/data`. If your change alters what the API reads from the lake, that bundle is stale until `just bundle-data` runs, and that command deletes and rewrites the shared `deploy/data`. Ask before running it; report the smoke result against the old bundle as such.
- `just api-smoke` deletes and rebuilds the worktree's `.venv-serve` each run (about 12 s with a warm uv cache). It never opens a port.
- The API loads the whole screen into memory at startup. A rebuilt mart is not served until you `$S stop` and `$S start-api` again. `$S doctor` flags it only when the row count or the build day changed, so restart after any rebuild.
- `/api/parcels/flagged` is built once per process and cached.
- Comps raise 503 when the baseline run's model files are missing; that is a lake problem, not an API bug.
- Locally `PHILLY_ENV` is unset, so the admin endpoint is open. Never set `PHILLY_ADMIN_TOKEN` in a verification shell; the smoke script unsets it.
