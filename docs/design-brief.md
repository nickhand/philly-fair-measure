# Design Brief, Philly Assessment Check

**For:** visual/product design pass (Claude Design)
**Scope:** redesign the look and feel of an existing, working Vue 3 + Tailwind v4 app. Information architecture, copy, and component behavior are settled and tested, this is a **design-system and visual-craft pass**, not a rebuild.

---

## 1. What this product is

A free public tool for Philadelphia residents: type your address, see whether the city's property assessment looks fair. Behind it is a serious independent valuation model; in front of it must be a page a rowhome owner in Kensington reads on a cracked phone screen and *trusts*.

It is a civic data product. It is not run by the city, but it should feel worthy of a city, an instrument of public accountability built with obvious care.

**The one-sentence design goal:** *the credibility of a government document, the clarity of a great newspaper graphic, the warmth of a neighbor explaining it to you.*

## 2. Naming (not yet finalized, help us land it)

The working name is **"Philly Assessment Check"**, functional, not final. Treat naming as part of this pass, not a fixed input.

**Criteria:** iconic, memorable, simple, straightforward. Explicitly **not weird**, no inside jokes, no forced puns, no reliance on regional slang an outsider wouldn't get instantly (this will be read by people who've never set foot in Philadelphia). It must sound credible enough to survive being printed and handed to a tax appeal board, or read by a skeptical city assessor's office, it cannot sound jokey, and it cannot sound like an official City of Philadelphia product (we are independent; the footer already discloses this, and the name shouldn't blur it). It's also a portfolio piece on a consultant's personal site, a little brand distinctiveness is welcome, never at the expense of credibility.

**Tone reference:** Zillow / Redfin / Trulia, simple, sayable, consumer real-estate-brand register, and ProPublica, civic-serious, short, credible. Not a punny startup name.

**Already explored and set aside** (too clever or too slang-forward for an anxious, plain-language audience): "Level Ground," "The Philly Ledger," "Fair Jawn," "Assessor Jawn" / "Jawnstimate."

**Current shortlist to react to or beat:** Fairly · Fair Philly · Worth / HomeWorth · Second Look · Philly Checkup · Property Check PHL.

**Ask:** propose ~10–15 additional candidates across a few registers, a single strong plain word, a two-plain-word phrase, a short descriptive phrase, one line of reasoning each, and flag anything that collides with an existing product name. Land on a direction as part of the wordmark deliverable (§8.3).

## 3. Audience and non-negotiables

- **Primary user:** a Philadelphia homeowner, median household income ~$60k, average adult reading level **8th grade**, likely on a mid-range Android phone. They arrived anxious about a tax bill.
- **Secondary users:** journalists, housing advocates, city staff checking our work.
- **Mobile-first.** Every layout must be designed at 375px first; desktop is the enhancement.
- **Accessibility is a hard floor:** WCAG 2.1 AA contrast minimum (AAA for body text preferred), color never the sole channel, visible focus states, 44px touch targets, `prefers-reduced-motion` variants, all charts keep their `role="img"` sentence-labels and `<details>` table fallbacks.
- **Reading level:** existing copy is written to 8th grade and centrally managed, do not rewrite verdict language (it is legally cautious on purpose: "may be too high," never "is too high").
- **No dark patterns, no tracking, no urgency theater.** The footer promise "no ads, no cookies, no analytics" is part of the brand.

## 4. Design direction: "civic craft"

Professional but civic-minded, operationally:

- **Feels like a public utility, not a startup.** No SaaS gradients, no glassmorphism, no marketing hero clichés. Restraint = credibility.
- **Feels like Philadelphia specifically.** The city flag is **azure blue and gold**, a legitimate, underused civic palette hook. phila.gov's own design language (their "Philadelphia blue" family + gold accent) is a useful reference point for *feeling official-adjacent* without imitating the city (we must not look like we ARE the city, that's both an ethics and a legal line; the footer disclaims it, the design shouldn't blur it).
- **Newspaper-graphics DNA for the data.** The charts should sit in the lineage of NYT Upshot / ProPublica / Urban Institute work: quiet axes, direct labeling, ink spent on data not chrome.
- **Government-design-system rigor.** USWDS and GOV.UK are the benchmark for forms, focus states, and plain-interface discipline. **Public Sans** (the USWDS open-source typeface) is a strong candidate exactly because of its civic provenance, consider it for UI, possibly paired with a serif display face (e.g., Source Serif) for headlines to get the "civic document" gravity. Self-hosted, subsetted, performance-budgeted (≤ ~120KB total webfont).
- **Trust furniture:** provenance lines ("Data updated 2026-07-04"), methodology links near every claim, the honest-caveat blocks, these are features, not fine print. Design them as first-class elements (consistent "honesty note" component), never buried.

## 5. Current state (what to improve)

The app works and follows the right patterns, but visually it's default-Tailwind generic: stock slate grays, one navy, emoji as icons (🏠 ⚖️ 📝 ⓘ ⚠), uniform rounded-2xl cards with no hierarchy between the verdict (the emotional payoff) and supporting panels, no wordmark, no visual identity.

Run it locally to see it: `uv run fair-measure api` + `cd web && npm run dev` → http://localhost:5173 (try address "108 ELFRETHS ALY"; map at /map; /methodology; /admin passphrase `philly-staff`).

Known specific weaknesses to solve:

1. **No identity.** Needs a wordmark/logotype (name still open, see §2) and a favicon/social card. Emoji must be replaced by a small consistent icon set (stroke style, e.g. Lucide, or a bespoke minimal set).
2. **The verdict moment is undersold.** "Your assessment looks fair / may be too high" is the product's emotional core. It currently renders as a small pill. It should be an unmistakable, screenshot-able moment, while staying calm and non-alarmist for the "too high" case (concern, not panic).
3. **Color system tension (resolve this):** brand navy (#163e75 family) vs. verdict semantics, **orange #c2410c = city value above our range, blue #1d4ed8 = below, slate = fair**. Verdict blue and brand blue currently read as the same family. Either shift the brand (e.g., toward flag azure+gold) or shift verdict-under's hue so the three verdict colors are unambiguous *and* colorblind-safe (the blue/orange opposition must survive; it's tested).
4. **Card monotony.** Everything is the same white rounded card. Establish hierarchy: verdict card ≫ analysis panels ≫ meta/provenance.
5. **The IntervalStrip** (band + best-estimate tick + city-value marker) is the signature graphic, currently functional but plain. Make it beautiful and instantly legible; it will be screenshotted and shared. Same visual language must extend to the peer histogram, driver bars, history sparkline, and the methodology explainer.
6. **Map styling.** Positron basemap + default dots. Wants: a dot/legend treatment consistent with the verdict palette, a designed bottom sheet, and a legend that doesn't look bolted on.
7. **States.** Skeletons, empty states, error states, and the search's "no matches" case need designed treatments (currently gray boxes and plain text).
8. **Print.** The property report will be printed and handed to an appeal board, provide a print stylesheet treatment (one page, black-safe, QR/URL back to the live page).

## 6. Page inventory (priority order)

1. **Property report** `/property/:id`, verdict card (headline moment), IntervalStrip, "what shapes our estimate" driver bars, "how you compare nearby" histogram, assessment history sparkline + sales, evidence chips, twin-uniformity callout, appeal on-ramp (facts table with ⚠ flags + free-appeal steps), provenance footer.
2. **Home** `/`, hero + address search (ARIA combobox, keep exact behavior), three "what you'll see" cards, citywide counters, honesty blurb.
3. **Map** `/map`, full-bleed map, floating search, legend, zoom hint, bottom sheet.
4. **Methodology** `/methodology`, long-form explainer with the interactive confidence-level widget (50/80/90/95% buttons over 80 dots), fairness comparison table, "what we cannot see" honesty section.
5. **Admin** `/admin`, staff tables; needs only tidying, deliberately utilitarian.
6. 404, loading, error states.

## 7. Hard technical contract (so the work drops in)

- **Stack:** Vue 3 SFCs + **Tailwind v4** (tokens live in `web/src/assets/main.css` under `@theme`). Deliver the palette/type/spacing/radius/shadow scale as a replacement `@theme` block.
- **Components to restyle** (paths are real): `App.vue` (header/footer), `views/*.vue` (5 pages above), `components/search/AddressSearch.vue`, `components/viz/{IntervalStrip,DriverBars,PeerHistogram,HistorySpark,IntervalExplainer}.vue`, `components/ui/{SectionCard,InfoTip,SkeletonBlock}.vue`, `components/map/PropertySheet.vue`.
- **Do not change:** component APIs/props, ARIA structure, verdict copy in `utils/verdict.ts` (hex values there MAY change, they feed the map, but the orange/blue semantic opposition and the tested "may" language must survive), the `<details>` chart fallbacks, the existing vitest assertions (17 tests must still pass; they test semantics and a11y, not pixels).
- **Performance budget:** ≤120KB webfonts subsetted & self-hosted, no image-heavy hero, LCP < 2.5s on a mid-range phone, everything else system-stack.

## 8. Deliverables requested

1. **Design tokens**, full Tailwind v4 `@theme` block: palette (brand + neutrals + the three verdict semantics + soft variants), type scale + faces, spacing, radii, shadows, motion durations.
2. **Typography spec**, faces, weights, sizes/line-heights for display/body/data (tabular numerals for all money).
3. **Naming direction + wordmark + favicon + social-card** (SVG), land the name per §2, then design its mark.
4. **Icon set choice** + the ~12 icons needed (search, map pin, scale/balance, document, check, warning, info, house, arrow, close, external, print).
5. **Redesigned key screens** (mobile 375px + desktop 1024px): property report, home, map w/ sheet open, methodology. Vue/Tailwind implementation preferred over mockups, this is a live codebase.
6. **Chart style guide**, the shared visual language for the five viz components (grid, labels, annotation style, the verdict-marker treatment).
7. **State treatments**, skeleton, empty, error, no-results, offline.
8. **Print stylesheet** for the property report.

## 9. Tone words

Steady · plainspoken · exacting · warm · Philadelphian · built-in-public.
Not: slick, corporate, playful-startup, bureaucratic-cold, alarmist.
