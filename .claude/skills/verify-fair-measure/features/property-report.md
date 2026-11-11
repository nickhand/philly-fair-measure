# Property search and report

A visitor types an address, picks a match, and lands on `/property/<parcel id>`, which shows the city's value next to the model's estimate and 90% range, a verdict, what drives the estimate, how the assessment compares with similar homes, assessment and sale history, and comparable sales loaded on request.

## Sub-features

- `search-suggest` lists matching addresses as the visitor types (debounced `/api/search`).
- `search-open` opens the report for the chosen address.
- `report-verdict` shows the address heading, `OPA #<id>`, the verdict headline, the city value and the estimate.
- `report-panels` shows "What shapes our estimate", "How your assessment compares nearby", "Assessment history" and "Other things we see in city data".
- `report-comps` loads "Comparable sales nearby" on the "Show comparable sales" button.
- `report-facts` shows "Check your facts, then decide" with each recorded fact and its effect.
- `report-condo` shows a "Condo unit" badge and same-building comps for a condo.
- `report-missing` shows "We could not find that property" for an unknown parcel id.

## How to get to it (user POV)

- Home page search box (label "Search your street address"), pick an option.
- Home page search box, then the "Check" button.
- The search box floating over `/map`, then a result.
- A direct link `/property/<parcel id>`, such as the "see on the map" round trip or a shared URL.

## Driving it with fm-verify

Preconditions:

- `$S start-api <slug>`, `$S build-site <slug>` and `$S start-preview <slug>` succeeded and `$S doctor <slug>` passes.
- Parcel `052174500` (108 ELFRETHS ALY) is `within_range` in the screen.

- **Search and open.** Type the address on Home and pick the match. Run `$S browse <slug> property-report / 'wait:heading:Is your home' 'fill:combobox:Search your street address=108 ELFRETHS' 'wait:option:108 ELFRETHS ALY' 'click:option:108 ELFRETHS ALY' 'wait:heading:108 ELFRETHS ALY' 'text:OPA #052174500' 'click:button:Show comparable sales' 'wait:table:Comparable sales the model used'`. Exit 0; `site/property-report.log.json` lists `200 .../api/search?q=108%20ELFRETHS`, `/api/property/052174500`, `/report` and `/comps`; `site/property-report-final.aria.txt` starts with `http://127.0.0.1:4173/property/052174500` and contains `heading "108 ELFRETHS ALY" [level=1]` and `heading "Your assessment is inside our range"`.
- **Comps table.** In the same run, the ARIA snapshot holds the table "Comparable sales the model used near this home" with 8 rows. Cross-check the rows against `$S get <slug> comps-052174500 /api/property/052174500/comps`.
- **Direct link.** Open the report without the search. Run `$S browse <slug> property-direct /property/591073500 'wait:heading:1154 E PRICE ST' 'text:OPA #591073500'`. The verdict heading reads `Your assessment may be too high` (an over-assessed parcel with no attention tier).
- **Condo.** Run `$S browse <slug> property-condo /property/888520502 'wait:heading:3600 CONSHOHOCKEN AVE #1001' 'text:Condo unit' 'click:button:Show comparable sales' 'wait:table:Comparable sales the model used'`. Distances in the table read `Same building`.
- **Unknown parcel.** Run `$S browse <slug> property-missing /property/000000000 'wait:heading:We could not find that property'`. Exit 0, and `site/property-missing.log.json` lists `404 http://127.0.0.1:8000/api/property/000000000` under `api`; `problems.http` holds the same 404 and `problems.console` a "Failed to load resource" line, both expected here, and the summary line counts the 404 among its HTTP errors.
- **Served shell.** `/property/<id>` has no prerendered HTML. Run `$S page <slug> property-shell /property/052174500` and check `site/property-shell.html` has an empty `<div id="app"></div>` (the `spa.html` shell); the content above came from the browser render.
- **Browser pane (optional, when the person watches).** `mcp__Claude_Browser__preview_start {url: "http://127.0.0.1:4173/"}`, `find "combobox"`, `computer left_click` the ref, `computer type "108 ELFRETHS"`, `find "option"`, click that ref, then `find "Show comparable sales"` and click it. Record the proof with the `$S browse` run above.

## Gotchas

- `npm run preview` answers same-origin `/api/*` with the SPA shell. A plain `npm run build` therefore shows no search results in the preview; build with `$S build-site`.
- The search debounces keystrokes. Wait for the `option`, not a fixed sleep.
- In the browser pane, options have no accessible name; `find "option"` and click the ref.
- Comps take about a second on the API; the button shows a skeleton first. Wait for the table.
- The verdict wording comes from `web/src/utils/verdict.ts` and depends on flag plus attention tier; assert the heading the snapshot shows, then confirm the flag with `$S get`.
