# Fair Measure — design handoff

Visual system: **"Flag & Ledger"** (direction 1a, converged in the design doc).
Everything here drops into the existing Vue 3 + Tailwind v4 app without touching
component APIs, props, ARIA structure, verdict copy, `<details>` fallbacks, or
test assertions.

Files in this folder:

| File | Replaces / role |
|---|---|
| `main.css` | `web/src/assets/main.css` — full `@theme` replacement |
| `verdict.ts` | `web/src/utils/verdict.ts` — hex values only; copy + class strings unchanged |
| `print.css` | new, imported by `main.css` — print treatment for the property report |
| `wordmark.svg` | header lockup (convert text to outlines before shipping) |
| `favicon.svg` | favicon (SVG favicon + 32px PNG fallback) |
| `social-card.svg` | og:image at 1200×630 (render to PNG at build) |

Reference mockups: `Design Explorations.dc.html` — 2a/2b (property report
mobile/desktop), 3a/3b (home), 3c (map + sheet), 3d (methodology), 3e (all four
verdict states), 3f (skeleton/error/no-results/offline).

---

## 1 · Naming

**Fair Measure** — plain, sayable, fairness + measurement, credible on a printed
appeal document, cannot be mistaken for a city product. Runner-up: Second
Opinion. Minor collision: "Fair Measures Inc." (corporate legal training) — 
different category; do a proper knockout search before committing domains.
Lockup: mark + "Fair Measure" + PHILADELPHIA overline. The mark IS the
IntervalStrip (band + estimate tick + gold city dot) — the product's signature
graphic as identity.

## 2 · Color system (resolution of the brand/verdict tension)

Brand moved to Philadelphia-flag **azure `#0f4d90` + gold `#f3c613`**; verdict
**under** shifted `#1d4ed8 → #0369a1` (cyan-leaning) so the three verdict hues
are unambiguous against the brand:

- `over #c2410c` / soft `#ffedd5` — city above range (unchanged, tested)
- `under #0369a1` / soft `#e0f2fe` — city below range (blue reading survives; deutan/protan-safe vs orange)
- `fair #46545f` / soft `#e6ebef` — inside range
- `none #8593a4` — no assessment

Gold is an **accent, never text on white** (fails contrast): 4px page-top rule,
favicon dot, sale markers (stroke `#8a6100` which IS text-safe), twin-uniformity
panel tint, focus rings on dark surfaces.

Chart grammar (all five viz components): **azure = our model; verdict color =
the city's number for you; gold = a real-world event (a sale)**.

## 3 · Typography

- **Public Sans** — everything by default. Weights 400 / 600 / 700 (+800 for wordmark & h1 if budget allows).
- **Source Serif 4** 700 — *verdict headline, page h1 on home/methodology only*. That scarcity is what makes the verdict feel like a document's finding.
- All money and axis numbers: `font-variant-numeric: tabular-nums`.
- Scale (px, mobile → ≥sm): caption 12 · body-sm 13 · body 15 · panel title 15–16/700 · address h1 23→30/800 · verdict headline 24→30 serif/700.
- Self-host, latin subset, woff2, `font-display: swap`; budget ≈ 112 KB (see `@font-face` stubs in `main.css`).

## 4 · Icons

Lucide, stroke 2 (2.4 at ≤14px), `stroke-linecap/join: round`, sized 16–20.
Replaces all emoji. Set used: `search, map-pin, scale, file-text, check,
triangle-alert, info, house, arrow-right, x, external-link, printer, wifi-off,
minus-circle, arrow-down`. Emoji ⚠ in the appeal table → `triangle-alert`
inline SVG, keeping `role="img"` + `aria-label="Looks unusual — double-check
this one"` from the current markup.

## 5 · Component restyle notes (by file)

**App.vue** — 4px gold top rule above header; white header, `border-line`
bottom; wordmark lockup replaces 🏠 + text; nav links: `rounded-sm px-3 py-2
text-[#334155]`, active `bg-brand-50 text-brand-600`. Footer: white, top
border, wordmark glyph + three existing paragraphs at `text-body-sm
text-muted`; links `font-semibold text-brand-600 underline`.

**SectionCard.vue** — `bg-white border border-line-soft rounded-lg p-4 sm:p-5`.
**No shadow** (hierarchy: only the verdict card gets `shadow-verdict`). Title
15–16px/700 ink; subtitle 12.5px muted.

**Verdict card (in PropertyView.vue)** — the headline moment:
`rounded-xl shadow-verdict border-line-soft overflow-hidden` with a **6px
verdict-color top bar**, 40px round icon chip in verdict-soft (triangle-alert /
check / arrow-down / minus-circle per flag), serif headline, **delta pill**
(`bg-over-soft text-over` etc.) stating the dollar gap: "$49,700 above our
highest estimate" — computed, not verdict copy. Then detail → IntervalStrip →
InfoTip → nextStep in a gold-tint panel (`bg-gold-tint border-gold-tint-border`,
arrow-right icon, 600 weight). See 3e for fair/under/none variants: same
anatomy, quieter color, no next-step panel emphasis.

**InfoTip.vue** — the "honesty note" component, first-class:
`bg-[#eef4fb] border-[#d8e4f2] rounded-md p-3 flex gap-2.5`, info icon in
brand-600, text 12.5–13px `text-body` color. With a `label` prop: label line
700 brand-600, body below. Gold variant (`bg-gold-soft border-gold-border`,
gold-700 icon/title) reserved for the twin-uniformity callout and "what we
cannot see".

**SkeletonBlock.vue** — shapes echo the verdict card (bar, circle, two lines,
band block); `.skeleton` class from `main.css` (1.6s shimmer, static under
reduced motion). See 3f.

**AddressSearch.vue** — 48px input, `border-[1.5px] border-[#b8c4d2]
rounded-md`; focused: `border-2 border-brand-600 ring-[3px] ring-brand-100`.
Attached "Check" button `bg-brand-600 text-white font-bold rounded-md`.
Listbox: white, `rounded-md shadow-popover`; active option `bg-brand-50`;
house icon per option; matched prefix `<strong>`. No-matches state: see 3f
(icon + "No matches for …" + plain-language format tip). ARIA/behavior
untouched.

**IntervalStrip.vue** — keep all geometry/ResizeObserver/a11y logic. Restyle:
band `fill #dbe7f5 stroke #b9d2ee rx 5–6`; estimate tick 3px `#0f4d90` with
label "Our estimate $NNN" 13px/700 azure above; city marker = triangle-down +
2px dashed drop line + 3.5px dot below band, all in `verdict.hex`, label
13px/700; range end labels 12px `#5d6b7c` below; caption "range we're 90% sure
about" 10.5px `#8593a4`. Keep grow-in animation at `--duration-chart` with
reduced-motion off-switch.

**DriverBars.vue** — diverging bars around a hairline center axis
(`#c6d0dc`): positive `#0f4d90`, negative `#9db1c7`; track `#eef1f5` rounded;
row = label (12–12.5px) · bar · tabular value (700; positive ink, negative
muted). Scale: widest bar = 48% of track.

**PeerHistogram.vue** — bins `#c9d9ec` rounded-top 1.5px; *your* bin
`#ffd9bd`; peer-median = solid 2px azure line, direct label "Similar homes'
middle NN%"; you = dashed 2px line in verdict color + dot, label "You NN%";
quiet baseline `#dfe5ec`; axis ticks 70/100/130%, caption "assessment as % of
our estimate". No y-axis, no gridlines.

**HistorySpark.vue** — 2.5px azure line, end dot + "$NNNK today" label; sales
= gold-stroke diamonds (`#8a6100`) + "Sold $NNNK"; baseline hairline; year
labels at ends + sale year.

**PropertySheet.vue** — `rounded-t-2xl shadow-sheet`, 38×4px drag handle,
address 17px/800 + OPA line, verdict badge pill, compact 64px strip (band +
tick + city dot, four labels), full-width 46px `bg-brand-600` CTA "See the full
report". See 3c.

**Map (MapView)** — dots use `verdict.hex` values (they already read from
verdict.ts); 6px radius, selected 9px + 3px white stroke. Legend: white pill
chips (dot + short semantic label "Above our range / Inside / Below"),
top-left under search — part of the map furniture, not a boxed panel. Floating
search `shadow-float rounded-[10px]`. Zoom hint: `bg-[rgba(22,36,58,.85)]`
white pill. Basemap: Positron as-is is acceptable; if budget allows, a custom
Positron-derived style with `#eef0f1` land / `#ccd8e2` water / white roads (as
in 3c) — still vector tiles, no perf cost.

**MethodologyView.vue** — see 3d: eyebrow "METHODOLOGY" 11px/700 letterspaced
azure; serif h1; confidence widget = segmented 40px buttons (active
`bg-brand-600` white) over the 80-dot grid (filled `#0f4d90`, misses
open-stroke `#9db1c7`), caption "72 of 80 sold inside the range"; fairness
table per 3d; "what we cannot see" in the gold honesty panel.

**AdminView** — utilitarian: paper bg, plain SectionCards, 13px tables,
tabular numerals, no verdict theatrics.

## 6 · States

- **Skeleton**: shapes echo target layout (3f); shimmer 1.6s; static + label under reduced motion.
- **Error**: white card, over-soft icon chip, existing error copy, 44px "Try again" primary button.
- **No matches**: popover panel, bold "No matches for '…'", format tip in plain language.
- **Offline**: muted card, wifi-off icon, "You're offline" + reload promise.
- **Empty panels**: keep existing one-line `text-body-sm text-muted` sentences (they're good); no illustrations.

## 7 · Print (`print.css`)

One Letter page, black-safe: color collapses to ink, verdict block gets a
2.5pt border, tints/shadows stripped, InfoTips + nav hidden, provenance line
with the **full live URL** auto-appended (no QR — photocopies kill QR codes;
if you want one anyway, put it at ≥0.9in with the URL beside it). Needs two
class hooks in PropertyView (`.report-root` with `data-parcel-id` /
`data-updated`, `.no-print` on nav/tips) — no structural changes.

## 8 · Performance & a11y checklist

- Fonts: 2 files, ~112 KB total, `swap`; system stack until loaded.
- No hero imagery; map tiles lazy on /map only.
- Focus: 3px azure ring (gold on dark), 44px touch targets, AA+ text
  (body `#425061` on white = 8.6:1), color never sole channel (markers differ
  by shape + label; flagged table rows get tint **and** icon **and** aria-label).
- All 17 vitest assertions: untouched copy, class strings, ARIA, `<details>` fallbacks.
