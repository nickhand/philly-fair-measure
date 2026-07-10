# Vertical-Equity Report Card

An honest, one-page answer to "how fair is it?", our model and OPA's roll scored
against the IAAO ratio-study standards, on two bases: the **IAAO-standard sample**
(what assessors are officially judged on) and the **full sample** (what actually
happens to every home, including the cash/distressed tail the standard excludes).

<!-- generated:veq-meta:begin -->
Numbers are the out-of-time test slice of baseline run
`20260708T000348Z-baseline` (n ≈ 19.5k residential arms-length sales).
Reproduce with `fair-measure train-baseline` then `fair-measure ratio-study`. This
report card is deliberately not a "we made it fair" claim, see the honest reading below.
<!-- generated:veq-meta:end -->

## The standards (IAAO Standard on Ratio Studies)

| Statistic | Measures | Acceptable |
|---|---|---|
| Median ratio | level of assessment | 0.90 – 1.10 |
| COD | uniformity (horizontal equity) | ≤ 15 single-family (higher tolerated for older/heterogeneous stock) |
| PRD | vertical equity | 0.98 – 1.03 |
| PRB | vertical equity (preferred) | within ±0.05; \|PRB\| > 0.10 unacceptable |
| VEI | vertical equity (primary test in the September 2025 exposure draft, §8.2.1) | −10% to +10%; beyond that a CI-gap significance test must stay ≤ 10% |

PRD > 1 / PRB < 0 / VEI < 0 = **regressive** (cheap homes over-assessed relative
to expensive). The VEI bins sales into percentile groups of a de-biased value
proxy (half sale price, half level-adjusted assessment) and compares the first
and last groups' median ratios to the sample median; our implementation
reproduces the draft's worked example exactly and is validated against it in
the test suite.

## Card 1, IAAO-standard basis (time-adjusted, 3×IQR-trimmed)

The convention on which an assessor's performance is officially measured.

<!-- generated:veq-card-iaao:begin -->
| Statistic | Target | OPA | Our model |
| --- | --- | --- | --- |
| Median ratio | 0.90–1.10 | 0.920 ✓ | 1.003 ✓ |
| COD | ≤ 15 | 23.1 ✗ | 18.7 ⚠︎ |
| PRD | 0.98–1.03 | 1.065 ✗ | 1.021 ✓ |
| PRB | ±0.05 | -0.057 ✗ | +0.007 ✓ |
| VEI (2025 draft) | −10% to +10% | -16.3% ✗ | +2.2% ✓ |
<!-- generated:veq-card-iaao:end -->

**Our model passes both vertical-equity tests (PRD and PRB) and sits just above
the uniformity target, where OPA fails all three.** The model's COD is
marginally over the strict single-family 15, but within the tolerance IAAO
allows for old, heterogeneous stock, which Philadelphia's rowhome fabric is. By
building style the model's trimmed COD is tightest on detached and twin homes
and loosest on rowhomes.

## Card 2, Full sample (out-of-time, no trim)

Every arms-length sale, including the cash and distressed tail. This is what a
homeowner actually experiences, and nobody passes it.

<!-- generated:veq-card-full:begin -->
| Statistic | Target | OPA | Our model |
| --- | --- | --- | --- |
| Median ratio | 0.90–1.10 | 0.983 ✓ | 1.036 ✓ |
| COD | ≤ 15 | 34.7 ✗ | 25.2 ✗ |
| PRD | 0.98–1.03 | 1.192 ✗ | 1.087 ✗ |
| PRB | ±0.05 | -0.235 ✗ | -0.084 ✗ |
| VEI (2025 draft) | −10% to +10% | -56.0% ✗ | -16.2% ✗ |
| MAPE | n/a | 34.2% | 26.3% |
<!-- generated:veq-card-full:end -->

On the full sample the model is still mildly regressive and above the uniformity
target, but carries a **fraction** of OPA's regressivity and much tighter
dispersion; compare the PRB and COD rows above.

## Card 3, Is the regressivity real, or a binning artifact?

A fair critique of any ratio-by-price-tier chart (Doucet,
[Vertical Inequity in property assessments: when is it real, when is it an illusion?](https://www.linkedin.com/pulse/vertical-inequity-property-assessments-when-real-illusion-lars-doucet-l2ame/)):
an individually mis-priced sale, a foreclosure or a family transfer that slipped
validation, lands in the bottom tier by construction and inflates its ratio,
even when no neighborhood is systematically over-assessed. The two questions
"are cheap *homes* over-assessed" and "are cheap *neighborhoods* over-assessed"
have the same chart but different answers. The artifact-robust version re-bins
each sale by the price level of its **neighborhood** instead of its own price:
a mis-validated bargain in a rich neighborhood moves to the top tier where it
belongs, while a systematically over-assessed poor neighborhood stays at the
bottom. Median assessment-to-price ratio in the cheapest and priciest fifth,
each way:

<!-- generated:veq-robustness:begin -->
| Basis | Binned by | City q1 | City q5 | Ours q1 | Ours q5 |
| --- | --- | --- | --- | --- | --- |
| all sales | individual price | 1.55 | 0.88 | 1.27 | 0.99 |
| all sales | **neighborhood level** | 1.17 | 0.93 | 1.02 | 1.05 |
| all sales | tract level (sensitivity) | 1.13 | 0.93 | 1.02 | 1.05 |
| financed | individual price | 1.24 | 0.88 | 1.10 | 0.99 |
| financed | neighborhood level | 0.97 | 0.92 | 0.93 | 1.04 |

Map test (kNN Moran's I of log ratios, financed sales): city 0.129, ours 0.092. Zero means errors sprinkle randomly; higher means they
cluster geographically, the signature of genuine neighborhood-level bias.

Neighborhoods are the 358 learned market areas with at least 50 arms-length sales
(median 485 sales behind each area's price level); 192 of 19,550 test sales sit in
areas below that threshold (or carry no area assignment) and are excluded
from the neighborhood-binned rows.
<!-- generated:veq-robustness:end -->

Reading it: neighborhood-level binning removes most of OPA's apparent
regressivity, so Doucet's artifact is real and large here. But the
remaining gap survives his own test, the cheapest fifth of *neighborhoods* is
still assessed well above what homes there sell for while the priciest fifth
sits below, and the city's errors cluster on the map. The model passes the same
test roughly flat. On the financed basis the city's neighborhood-binned gap
nearly closes, which locates its remaining inequity in how the cash and
distressed channel is treated at neighborhood level (see
[report-assessment-equity.md](report-assessment-equity.md)). Reproduce with
`fair-measure equity-robustness`; the same tests run on any jurisdiction's data
at [OpenRatioStudy.com](https://www.openratiostudy.com), and
`fair-measure export-ratio-csv` writes our exact test set (sale, valuation,
coordinates, market area) in its input format for an independent cross-check.

## The honest reading

1. **The gap between the two cards is the whole story.** Going from full to
   IAAO-standard drops the model's COD and PRB toward the bands. That
   improvement is not the model getting fairer, it is the **3×IQR trim removing
   the cash/distressed tail**. The mainstream way jurisdictions "pass" is to
   exclude exactly those sales (foreclosures, non-arms-length, extreme ratios).
   So "IAAO-compliant" and "fair to cash-market neighborhoods" are different
   claims; the standard is computed on the sales it doesn't exclude.

2. **What we can honestly say:** on identical footing, the model is more
   accurate, more uniform, and markedly less regressive than OPA, on *every*
   basis, trimmed or not, and it clears the IAAO vertical-equity bands on the
   standard basis, which OPA does not.

3. **What we cannot say:** that it is "fair." The residual, full-sample
   regressivity, the cash-market homes taxed above realizable value, the
   dispersion (COD) that no current AVM drives below ~15 on this stock, is real
   and is stated here rather than trimmed away.

4. **OPA is not gaming the ratio study.** The sale-chasing check
   (`assesspy.is_sales_chased`) returns false across TY2025/2026, before and
   after certification, and OPA's regressivity is stable across those windows.
   Its regressivity is genuine mass-appraisal regressivity, the structural kind
   documented nationwide ([research-notes.md](research-notes.md),
   [report-assessment-equity.md](report-assessment-equity.md)), not a
   sales-selection artifact.

## Context: this is a national, structural problem

Property-assessment regressivity is "almost universal", Berry's national sample
of ~26M sales finds the bottom decile assessed roughly twice as high (relative to
price) as the top; it persists regardless of policy and even within a single
school district. So the frame is not "OPA is uniquely bad" but "OPA sits at the
regressive end of a structural problem, and a better model plus an equitable
appeals process moves it, most of the way on vertical equity, not all the way on
uniformity." See [report-assessment-equity.md](report-assessment-equity.md) for
the racial/economic decomposition and the cash/financed channel analysis.
