# Record-quality stress test: 2537 N 7th and 2632 N 5th

Investigated 2026-07-13 against the local raw/staged snapshots and the public
sources linked below. Parcel/account identifiers are 371063501 and 192222401.

## 2537 N 7th St: legitimate distressed sale plus active conversion

- RTT records a $70,000 sale on 2025-01-09. The sale is plausibly arms-length;
  the problem is not that the price is fake, but that it represents a shell.
  The sale listing said the building needed major renovation, was sold as-is,
  and could not be entered for inspection.
- OPA currently records condition 7/7 (sealed or structurally compromised),
  1,494 square feet, and one story. PWD describes a three-story masonry row;
  the building-footprint layer measures 541 square feet and about 31 feet high,
  also supporting roughly three stories.
- Building permit CP-2025-000462 was issued 2025-05-06 for Level III interior
  alterations and change of occupancy to three dwelling units. It remains
  `Issued`, with neither completion nor certificate-of-occupancy date in the
  snapshot. Plumbing, fire-suppression, and mechanical permits also remain
  issued; two electrical permits completed in May 2026.
- A 2026-02-27 L&I complaint described the unoccupied building as structurally
  deficient. It closed the next day; closure does not demonstrate renovation
  completion.
- The old model's largest positive driver was undifferentiated recent permits
  (about +$77,500). It therefore treated active gut-conversion evidence as if
  it were completed renovation evidence.

Decision: retain the sale as a real distressed transaction, but split model
features into completed permits, active permits, completed renovation permits,
active renovation permits, and active change-of-occupancy permits. The public
assessment screen withholds a verdict while a recent current-status `Issued`
change-of-occupancy permit remains incomplete. The estimate and broader range
remain visible with a prominent data warning, but are not presented as a
defensible over/under conclusion.
On the six held-out sales with this active-occupancy-change pattern, the revised
model improves log-RMSE from 0.487 to 0.366 and moves median prediction/sale
from 1.236 to 1.078; citywide log-RMSE is effectively flat (0.3211 to 0.3213).
In the refreshed assessment screen its deterministic calibrated estimate moves
from about $216,000 to $196,000, but `insufficient_record` intentionally
replaces the former under-assessment verdict while the conversion is open.

## 2632 N 5th St: internally inconsistent OPA characteristics

- OPA calls the property a three-story converted-row multi-family building,
  but records only 924 total living square feet and zero bedrooms/bathrooms.
- The official footprint is 858 square feet and about 34 feet high. Three
  floors imply about 2,574 gross square feet; recorded living area is only
  35.9% of that independent gross-area proxy.
- A completed 2018 permit describes a two-family building. There is no current
  open permit or current distress evidence comparable to 2537.
- The owner is Philadelphia Housing Authority and the $233,400 OPA value is
  fully exempt. This is useful market-value QA, but not a normal homeowner tax
  appeal case.

Decision: preserve both measurements and flag the conflict; do not replace 924
with 2,574. A valuation ablation using footprint area, height, discrepancy, and
a footprint-scaled neighborhood price anchor failed validation: on 26 held-out
sales with the same conservative conflict pattern, log-RMSE worsened from
0.390 to 0.429 and median prediction/sale rose from 1.058 to 1.150. The record
therefore receives no numeric assessment verdict until a better characteristic
source or a verified unit/living-area record is available. The footprint
conflict is excluded from the Bayesian mean but included in its variance. The
learned log-sigma effect is 0.223 (90% posterior interval 0.049–0.420), about
25% higher residual standard deviation; the refreshed Bayesian interval for
this parcel is approximately $29,000–$246,000. This quantifies the uncertainty
without pretending the footprint-derived gross area is finished living area.
The estimate and this wider interval are displayed; only the comparison verdict
is suppressed.

## Production rules added

1. Permit existence is no longer a model input. Completion state is.
2. Active change-of-occupancy work is modeled separately from completed
   renovation.
3. Footprint/height measurements and OPA living area are both preserved;
   neither overwrites the other.
4. A multi-family area conflict requires zero beds and baths, OPA and height
   support for at least two stories, story estimates within one floor, a main
   footprint of at least 200 square feet, and recorded living area below 40%
   of footprint times stories.
5. The screen also withholds a verdict for a change-of-occupancy permit issued
   within two years that remains `Issued` in the current snapshot.

## Sources

- OpenDataPhilly, [L&I building permits](https://opendataphilly.org/datasets/licenses-and-inspections-building-permits/)
- Philadelphia ArcGIS, [official building-footprint service](https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/LI_BUILDING_FOOTPRINTS/FeatureServer/0)
- Redfin/MLS mirror, [2537 N 7th St sale record](https://www.redfin.com/PA/Philadelphia/2537-N-7th-St-19133/home/39473619)
- ProPublica HUD inspection data, [PHA scattered-sites property list](https://projects.propublica.org/hud/properties/PA002000905)

External listing text is corroborating evidence only; the production rules use
official structured city data. Footprints and OPA characteristics are
current-only and must not be treated as historically correct at old sale dates.
