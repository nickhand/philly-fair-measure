# Assessment map

`/map` shows every flagged and watch-tier home in Philadelphia as colored dots at city zoom, every home once zoomed to street level, legend chips that hide or show each result, a condo filter, an address search, and a property sheet for a chosen home.

## Sub-features

- `map-overview` loads the citywide flagged payload (`/api/parcels/flagged`) and draws it.
- `map-legend` toggles dots by result: "Above our range", "Leaning high", "Inside our range", "Data warning", "Leaning low", "Below our range", plus "Condos".
- `map-street` fetches every home in the viewport (`/api/parcels?minx=...`) once zoomed in.
- `map-deeplink` opens and centers one home from `/map?parcel=<id>` with its property sheet.
- `map-search` moves to an address chosen in the floating search box.

## How to get to it (user POV)

- "Map" in the top navigation.
- "see on the map" on a property report (`/map?parcel=<id>`).
- A direct URL `/map`.

## Driving it with fm-verify

Preconditions:

- `$S start-api <slug>`, `$S build-site <slug>` and `$S start-preview <slug>` succeeded and `$S doctor <slug>` passes.
- Internet access for `tiles.openfreemap.org`.

- **Overview loads.** Open the map and wait for the loading overlay to clear. Run `$S browse <slug> map-flagged /map 'wait:heading:Assessment map of Philadelphia' 'gone:Loading the map' 'text:Showing flagged homes' 'wait:group:Show or hide homes by result'`. Exit 0; `site/map-flagged.log.json` lists `200 http://127.0.0.1:8000/api/parcels/flagged`; `site/map-flagged-final.png` shows colored dots over Philadelphia; the ARIA snapshot shows every legend chip `[pressed]` except "Inside our range".
- **Payload matches the screen.** Run `$S get <slug> parcels-flagged /api/parcels/flagged`, then count features: `python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['features']))" "$($S evidence <slug>)/api/parcels-flagged.json"`. Recount from the marts (screen rows flagged over or under, or with an attention tier, that have coordinates in `assessment_features` or `condo_assessment_features`); on the 2026-07-14 lake both give 47,623.
- **Legend toggle.** Hide over-assessed homes. Run `$S browse <slug> map-legend /map 'gone:Loading the map' 'click:button:Above our range' 'snap:above-hidden'`. In `site/map-legend-above-hidden.aria.txt` the chip `button "Above our range"` has lost `[pressed]`; compare `map-legend-above-hidden.png` with `map-flagged-final.png`.
- **Deep link.** Open one home from a URL. Run `$S browse <slug> map-deeplink '/map?parcel=591073500' 'gone:Loading the map' 'wait:dialog:1154 E PRICE ST'`. Expected: the URL stays on `/map`, the dialog named after the address is open, and the log lists `200 .../api/property/591073500`. This journey fails at `ae7a681` (see Gotchas).
- **Viewport fetch.** Street-level dots need a zoom the headless driver does not perform. Prove the endpoint instead: `$S get <slug> parcels-bbox '/api/parcels?minx=-75.17&miny=39.94&maxx=-75.14&maxy=39.96'` returns a FeatureCollection with more than 100 features. Report the in-map zoom path as not driven.

## Gotchas

- "Showing flagged homes" appears before the map is ready. Wait for "Loading the map" to disappear (`gone:`), or the screenshot is a spinner.
- The flagged payload is about 10 MB uncompressed (47,623 features on the 2026-07-14 lake); first paint takes a few seconds.
- In a hidden desktop browser pane the map can stall at "Loading the map…", and `read_network_requests` may not list the GeoJSON fetch. Use `$S browse` for proof.
- The headless driver runs system Chrome with WebGL; a `pageerror` about WebGL in `map-*.log.json` means the environment, not the app, failed. Report it as unverified.
- The cold deep link `/map?parcel=<id>` (the report's "see on the map" link) lands on `/property/<id>` instead of opening the sheet. Observed twice on 2026-11-11 at `ae7a681`, for `591073500` and `052174500`. The likely cause, read from `MapView.vue` and not instrumented, is that `openParcel` calls `setFilter` before the style has loaded, the throw is caught as a failed lookup, and `focusParcel` falls back to `router.push` to the report. Report this journey as failing until a fix lands; do not drop the step.
- Dots are canvas pixels with no accessible handles. Assert through the legend chips, the dialog, and the API responses, never by clicking coordinates.
