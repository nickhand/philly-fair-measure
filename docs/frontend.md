# The Front Door: public dashboard (`web/`) + JSON API

The public-facing piece of the project: a resident enters their address and
gets their assessment analysis, the screen verdict with its 90% interval, the
value drivers, the neighborhood equity comparison, assessment history, and a
plain-language appeal on-ramp. Design brief: mobile-first, accessible,
**8th-grade reading level** (Philadelphia's adult average), honest about
uncertainty, and free, the product features (leaderboards) live in an
unlinked staff view, not the public flow.

## Architecture

```
web/                    Vue 3 + TypeScript + Vite + Tailwind v4 (mobile-first)
  src/api/              typed client + response types (mirror api.py pydantic)
  src/utils/verdict.ts  THE single source of plain-language verdict copy/colors
  src/components/viz/   custom SVG viz (d3-scale only): IntervalStrip,
                        DriverBars, PeerHistogram, HistorySpark, IntervalExplainer
  src/views/            Home (search), Property (report), Map, Findings,
                        Methodology, Trust (The Proof), Appeal,
                        Admin (staff, unlinked), NotFound

src/philly_fair_measure/api.py   FastAPI over the marts
  startup: assessment_screen + coordinates loaded once into memory (~500k rows)
  /api/search            address autocomplete (case-insensitive, prefix-ranked)
  /api/property/{id}     fast core: verdict, values, interval, signals
  /api/property/{id}/report   drivers (TreeSHAP), equity + peer histogram,
                              assessment/sale history (~1s; booster loaded per call)
  /api/property/{id}/comps    leaf-similarity comparable sales
  /api/parcels?bbox      GeoJSON points for the map viewport
  /api/parcels/flagged   citywide flagged parcels (map overview layer)
  /api/stats             home-page counters
  /api/admin/leaderboard staff worklists (see Security)
```

Run it:

```bash
uv run fair-measure api            # backend on :8000
cd web && npm install && npm run dev   # frontend on :5173, /api proxied
```

Tests/gates: `npm run test:unit` (vitest: viz semantics, ARIA combobox
behavior, verdict copy), `npm run type-check`, `npm run lint`, `npm run build`;
Python side `uv run pytest tests/test_api.py`.

## Design decisions

- **Verdict language is centralized** (`utils/verdict.ts`) and tested: flags
  are *candidates*, so the copy must hedge ("may be too high"), a test
  enforces the "may". Orange/blue verdict pair is colorblind-safe; color is
  never the only channel (labels/shapes carry meaning).
- **Raw model values never reach residents.** The API renders driver values
  via `explain.display_value()`, the `_VALUE_UNITS` gate, so "1,120 sq ft"
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
- **Map wiring is `styledata`-based, not `load`-based**, `load` waits for
  every glyph and can stall (or never fire in embedded browsers); wiring is
  idempotent and `moveend` attaches unconditionally. Dots appear at zoom
  ≥14.5 via bbox queries; below that, a hint. Bottom sheet on tap; map
  controls sit top-right so the sheet never covers them; the address search
  overlay is the accessible non-map path.
- **Analytics, minimally.** PostHog with autocapture and session recording
  OFF, cookieless (localStorage persistence), manual pageviews + a small set
  of named events (address_selected, report_viewed, comps_shown,
  report_printed, map_parcel_opened, map_filter_toggled); prod builds only.
  The footer says "no ads, no cookies, anonymous usage statistics".

## Scaling / deploy path (not yet done)

- **Vector tiles**: the bbox endpoint is fine for a single host; for static or
  high-traffic deploys, bake the screen to PMTiles
  (`tippecanoe -o parcels.pmtiles` over exported GeoJSON) and swap the map
  source, `pmtiles` is already a dependency; MapView is written so the source
  swap is contained.
- **Report latency**: `/report` reloads the booster per call (~1s). Memoize
  the loaded model + mappings in app state before real traffic.
- **Basemap**: OpenFreeMap Positron (no key, ODbL attribution shown). For a
  production SLA, self-host the style or pin a paid tile provider.

## Tufte pass (2026-07-05)

A review of every page against Tufte's principles; what changed and what was
deliberately kept:

- **Show the data.** The verdict card now states the two headline figures as
  text (City's value / Our estimate) above the IntervalStrip, the numbers
  survive printing, screen readers, and screenshots without the chart.
- **Maximize data-ink.** DriverBars' gray track backgrounds removed (the
  center hairline is the zero axis; bars carry all information). Charts keep
  no gridlines, no borders, ≤3 axis ticks, direct labels instead of legends
  (HistorySpark labels each sale on the mark; PeerHistogram labels "You" and
  the peer median in place).
- **Label integrity.** All chart annotations clamp or flip at the plot edges
  (no cut-off text) and resolve collisions when the city value and the
  estimate sit close (IntervalStrip slides the estimate label off the city
  drop-line; the map sheet staggers "City" onto a second row).
- **Tabular numerals everywhere** money or ratios align vertically.
- **Kept, with reasons:** the interval band's soft fill (it *is* data, the
  90% range); the peer histogram's your-bin highlight (comparison is the
  point); the gold sale diamonds (chart grammar: gold = a real-world event).

## Product notes

- `/leaderboards` (alias `/admin`) is the review-worklist page, planned to move
  behind a real paywall/admin login when the product tier ships; the current
  passphrase is a placeholder only.
- Site-wide links (creator credit → nickhand.dev, GitHub repo, technical model
  docs) live in `web/src/config/site.ts`.

## Headline stats pipeline

Every measured figure on Findings / The Proof / Methodology comes from
`web/src/data/siteStats.json`, generated by `fair-measure export-web-stats` from the
latest baseline run's artifacts + the marts (full-sample card, financed IAAO
card via the assesspy 3×IQR trim, financed tier ratios, cash/financed
structure, the historical redistribution series). Regenerate after every
retrain or screen rebuild, the views interpolate the JSON and must never be
hand-edited. Provenance (run id + generation date) renders on both pages.

## Security

- `/api/admin/*` requires the `PHILLY_ADMIN_TOKEN` bearer token
  (`_require_admin` in api.py; `just fly-secrets` sets it in production). The
  `/admin` view's client-side passphrase remains a convenience gate only, the
  server-side token is the real access control.
- CORS uses an allowlist from `PHILLY_CORS_ORIGINS` (api.py); dev uses the
  Vite proxy.

## Known limitations

- Condo properties get a reduced report (no TreeSHAP drivers/equity, the
  condo model has no explain arm yet).
- The peer histogram uses same-ZIP + similar-value peers (mirrors
  `equity_context`'s rule), thin ZIPs fall back to ZIP-wide.
- The methodology page's fairness numbers interpolate `siteStats.json` like
  every other measured figure (see "Headline stats pipeline" above); the
  vitest guard `no-hardcoded-stats.spec.ts` fails the suite when a stat is
  typed as a literal instead.
