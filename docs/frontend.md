# The Front Door: public dashboard (`web/`) + JSON API

The public-facing piece of the project: a resident enters their address and
gets their assessment analysis — the screen verdict with its 90% interval, the
value drivers, the neighborhood equity comparison, assessment history, and a
plain-language appeal on-ramp. Design brief: mobile-first, accessible,
**8th-grade reading level** (Philadelphia's adult average), honest about
uncertainty, and free — the product features (leaderboards) live in an
unlinked staff view, not the public flow.

## Architecture

```
web/                    Vue 3 + TypeScript + Vite + Tailwind v4 (mobile-first)
  src/api/              typed client + response types (mirror api.py pydantic)
  src/utils/verdict.ts  THE single source of plain-language verdict copy/colors
  src/components/viz/   custom SVG viz (d3-scale only): IntervalStrip,
                        DriverBars, PeerHistogram, HistorySpark, IntervalExplainer
  src/views/            Home (search), Property (report), Map, Methodology,
                        Admin (staff, unlinked), NotFound

src/philly_assessments/api.py   FastAPI over the marts
  startup: assessment_screen + coordinates loaded once into memory (~500k rows)
  /api/search            address autocomplete (case-insensitive, prefix-ranked)
  /api/property/{id}     fast core: verdict, values, interval, signals
  /api/property/{id}/report   drivers (TreeSHAP), equity + peer histogram,
                              assessment/sale history (~1s; booster loaded per call)
  /api/parcels?bbox      GeoJSON points for the map viewport
  /api/stats             home-page counters
  /api/admin/leaderboard staff worklists (see Security)
```

Run it:

```bash
uv run philly api            # backend on :8000
cd web && npm install && npm run dev   # frontend on :5173, /api proxied
```

Tests/gates: `npm run test:unit` (vitest: viz semantics, ARIA combobox
behavior, verdict copy), `npm run type-check`, `npm run lint`, `npm run build`;
Python side `uv run pytest tests/test_api.py`.

## Design decisions

- **Verdict language is centralized** (`utils/verdict.ts`) and tested: flags
  are *candidates*, so the copy must hedge ("may be too high") — a test
  enforces the "may". Orange/blue verdict pair is colorblind-safe; color is
  never the only channel (labels/shapes carry meaning).
- **Raw model values never reach residents.** The API renders driver values
  via `explain.display_value()` — the `_VALUE_UNITS` gate — so "1,120 sq ft"
  shows but log-surface/tract-code internals return `None` (a raw
  `493924.5028732775` erodes trust; we saw it happen in smoke testing).
- **Every chart has a text fallback**: `role="img"` with a full-sentence
  label, plus a `<details>` data table. Search implements the WAI-ARIA
  combobox pattern; route changes move focus to the new `h1`; skip link;
  `prefers-reduced-motion` honored.
- **The interval is the story.** The property page leads with the
  IntervalStrip (band + best estimate + city value); the methodology page has
  an interactive explainer (50/80/90/95% buttons over 80 simulated sales)
  teaching what "90% sure" means.
- **Map wiring is `styledata`-based, not `load`-based** — `load` waits for
  every glyph and can stall (or never fire in embedded browsers); wiring is
  idempotent and `moveend` attaches unconditionally. Dots appear at zoom
  ≥14.5 via bbox queries; below that, a hint. Bottom sheet on tap; map
  controls sit top-right so the sheet never covers them; the address search
  overlay is the accessible non-map path.
- **No tracking.** No analytics, no cookies; the footer says so.

## Scaling / deploy path (not yet done)

- **Vector tiles**: the bbox endpoint is fine for a single host; for static or
  high-traffic deploys, bake the screen to PMTiles
  (`tippecanoe -o parcels.pmtiles` over exported GeoJSON) and swap the map
  source — `pmtiles` is already a dependency; MapView is written so the source
  swap is contained.
- **Report latency**: `/report` reloads the booster per call (~1s). Memoize
  the loaded model + mappings in app state before real traffic.
- **Basemap**: OpenFreeMap Positron (no key, ODbL attribution shown). For a
  production SLA, self-host the style or pin a paid tile provider.

## Security — MUST fix before public deploy

- `/api/admin/*` endpoints are **unauthenticated**, and the `/admin` view's
  passphrase is a **placeholder gate, not auth** (it's in the client bundle).
  Put real auth in front (or strip the admin router) before exposure.
- CORS is not configured (dev uses the Vite proxy); add an allowlist when the
  API gets its own origin.

## Known limitations

- Condo properties get a reduced report (no TreeSHAP drivers/equity — the
  condo model has no explain arm yet).
- The peer histogram uses same-ZIP + similar-value peers (mirrors
  `equity_context`'s rule) — thin ZIPs fall back to ZIP-wide.
- Copy hardcodes the fairness table numbers on the methodology page from the
  2026-07 measured run; regenerate when the model is retrained.
