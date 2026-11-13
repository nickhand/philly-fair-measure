# Published pages and numbers

Six pages are prerendered to HTML at build time: Home (`/`), the Tax Year 2027 report (`/reports/ty-2027`, alias `/report`), Findings, Methodology ("How this works"), Trust ("Why trust these numbers") and Appeal. Every statistic they print comes from the committed `web/src/data/siteStats.json`, which `fair-measure export-web-stats` computes from the lake. Home also refreshes its three counters from `/api/stats` after it mounts.

## Sub-features

- `home-counters` prints "homes we valued citywide" (`screen.properties`), "flagged outside our range" (`screen.over + screen.under`) and "more worth a closer look" (`screen.watch`).
- `home-refresh` replaces those counters with the live `/api/stats` values in the browser.
- `page-copy` prerenders each page's headings and prose into `web/dist/<page>.html`.
- `page-meta` gives each page one title, description, canonical URL and social tags (checked by `web/scripts/check-prerender-output.mjs`).
- `stats-source` keeps run-dependent numbers bound to `siteStats.json` (guarded by `web/src/__tests__/no-hardcoded-stats.spec.ts`) and the README/model.md blocks in sync (`fair-measure sync-docs --check`).

## How to get to it (user POV)

- The top navigation: "2027 Report", "Findings", "Methods", "The Proof", "Appeal", and the logo for Home.
- The footer links: "2027 assessment report", "What we found", "How it works", "Why trust these numbers".
- Search engines and shared links land on the prerendered HTML directly.

## Driving it with fm-verify

Preconditions:

- `$S build-site <slug>` succeeded; `logs/site-build.log` ends with `Verified 6 pre-rendered pages, the report alias, per-page metadata, neutral deadlines, and SPA fallback.`
- For the served and browser checks, `$S start-preview <slug>` and `$S start-api <slug>` are up.

- **Built copy.** Capture the page a crawler or first paint gets. Run `$S page <slug> findings /findings`, then `grep -c 'Philadelphia has two housing markets.' "$($S evidence <slug>)/site/findings.html"`. Count `1` or more. Use the exact sentence your change introduced; a match in `web/src/views/*.vue` proves nothing.
- **All prerendered pages.** Run `$S page` for `/`, `/reports/ty-2027`, `/report`, `/findings`, `/methodology`, `/trust` and `/appeal`. Each returns 200 and contains `data-server-rendered="true"`.
- **Home counters re-measured.** Run `$S remeasure <slug> --api http://127.0.0.1:8000 --html web/dist/index.html`. Exit 0 with `remeasure: OK`; the checks include `index.html shows '496,975 homes we valued citywide'`, `'7,435 flagged outside our range'` and `'40,200 more worth a closer look'`, matched in the page's visible text (comments, attributes, scripts and styles dropped) with each count next to its label.
- **Live refresh.** Run `$S browse <slug> home / 'wait:heading:Is your home' 'text:homes we valued citywide'`. The log lists `200 http://127.0.0.1:8000/api/stats`, and the ARIA snapshot shows the same three numbers as `/api/stats`.
- **Other statistics.** For a number on Findings, Trust, Methodology or the report, find its key in `siteStats.json` (`grep -n` the printed value), recompute it with `$S cli <slug> export-web-stats export-web-stats --out "$($S evidence <slug>)/siteStats.json"`, diff the two JSON files (on an unchanged lake only `meta.generated_at` differs), and grep the built page for the formatted value. That proves the number reproduces with the code under test. When the change alters how the number is computed, also recount it with an independent polars query on the mart.
- **Docs blocks.** Run `$S cli <slug> sync-docs sync-docs --check`. It prints `docs in sync with siteStats.json`.

## Gotchas

- `npm run dev` renders in the browser only; it never proves prerendered HTML. Use the built `web/dist`.
- Prerendered text can split across tags. Grep for a phrase inside one element, or read the `$S browse` ARIA snapshot.
- Home prints `siteStats.json` values at build time and the API values after mount. A mismatch between them means the lake moved since the last `export-web-stats`, which is a finding, not a flake.
- `export-web-stats` without `--out` rewrites the committed `web/src/data/siteStats.json`, and `sync-docs` without `--check` rewrites README.md and docs/model.md. Only run them that way when the change is a stats refresh.
- The Appeal page and the timing banner compute deadlines after mount in Philadelphia time; the prerendered HTML deliberately has neutral wording (`check-prerender-output.mjs` asserts it).
