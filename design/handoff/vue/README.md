# handoff/vue — Vue SFC implementations

Restyled components matching the design doc (turns 2–3) and the copy in the
mocks exactly. Paths mirror `web/src/`. Requires `handoff/main.css` +
`handoff/verdict.ts` to be in place first (the classes reference its tokens:
`text-ink`, `bg-paper`, `border-line-soft`, `shadow-verdict`, `font-display`…).

## Drop-in (source was available — safe to replace)
- `App.vue` — header/footer restyle; copy identical, name → Fair Measure.
- `views/PropertyView.vue` — copy, data flow, ARIA, `<details>` all preserved.
  Added: verdict-card anatomy, computed delta pill, `.report-root`/`.no-print`
  print hooks, Lucide-style inline SVG replacing the ⚠ emoji (same
  `role="img"` + `aria-label`).
- `components/viz/IntervalStrip.vue` — original logic (ResizeObserver, scale,
  aria sentence, table fallback) with the new visual treatment.

## Inferred contracts (I never saw the original source — verify before replacing)
Each file header states what was assumed:
- `components/ui/SectionCard.vue`, `InfoTip.vue`, `SkeletonBlock.vue` — props
  inferred from PropertyView usage. InfoTip gained an optional
  `variant="gold"` (used nowhere by default).
- `components/viz/DriverBars.vue` — assumes `{ label, dollars }[]`.
- `components/viz/PeerHistogram.vue` — assumes bins `{ from, to, count }[]`.
- `components/viz/HistorySpark.vue` — assumes `{ year, value }[]` +
  `{ date, price, validity }[]`.
- `components/search/AddressSearch.vue` — **your combobox behavior is tested;
  prefer porting these classes onto your existing component** rather than
  replacing it. Assumes `api.search(q)`.
- `components/map/PropertySheet.vue` — assumes `core: PropertyCore` prop +
  `close` emit.
- `views/MapView.vue` + `map/fairMeasureMapStyle.ts` — Positron restyled via
  paint-property overrides (no custom tiles, no perf cost); dot colors come
  from `VERDICTS[*].hex` so map and verdicts can never drift. Replace the
  placeholder `'/api/map/parcels.geojson'` source with your real one and set
  the right `minzoom`.
- `views/HomeView.vue`, `views/MethodologyView.vue` — copy matches the mocks;
  counter values and fairness-table figures are SAMPLE numbers (marked TODO).

## After integrating
Run the vitest suite (17 tests). If a viz prop shape differs from my
assumption, keep your component's script and port only the `<template>`/class
changes — the visual spec is in `HANDOFF.md` §5.
