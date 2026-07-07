# Vertical-Equity Report Card

An honest, one-page answer to "how fair is it?", our model and OPA's roll scored
against the IAAO ratio-study standards, on two bases: the **IAAO-standard sample**
(what assessors are officially judged on) and the **full sample** (what actually
happens to every home, including the cash/distressed tail the standard excludes).

Numbers are the out-of-time test slice of baseline run
`20260705T015912Z` (n ≈ 19.5k residential arms-length sales). Reproduce with
`fair-measure train-baseline` then `fair-measure ratio-study`. This report card is
deliberately not a "we made it fair" claim, see the honest reading below.

## The standards (IAAO Standard on Ratio Studies)

| Statistic | Measures | Acceptable |
|---|---|---|
| Median ratio | level of assessment | 0.90 – 1.10 |
| COD | uniformity (horizontal equity) | ≤ 15 single-family (higher tolerated for older/heterogeneous stock) |
| PRD | vertical equity | 0.98 – 1.03 |
| PRB | vertical equity (preferred) | within ±0.05; \|PRB\| > 0.10 unacceptable |

PRD > 1 / PRB < 0 = **regressive** (cheap homes over-assessed relative to expensive).

## Card 1, IAAO-standard basis (time-adjusted, 3×IQR-trimmed)

The convention on which an assessor's performance is officially measured.

| Statistic | Target | OPA | Our model |
|---|---|---|---|
| Median ratio | 0.90–1.10 | 0.938 ✓ | 0.972 ✓ |
| COD | ≤ 15 | 25.4 ✗ | 17.0 ⚠︎ |
| PRD | 0.98–1.03 | 1.115 ✗ | **1.029 ✓** |
| PRB | ±0.05 | −0.148 ✗ | **−0.022 ✓** |

**Our model passes both vertical-equity tests and is just above the uniformity
target; OPA fails all three.** COD 17 is marginally over the strict single-family
15, but within the tolerance IAAO allows for old, heterogeneous stock, which
Philadelphia's rowhome fabric is. By building style, the model's trimmed COD is
15.1 (detached) / 15.3 (twin) / 17.4 (row).

## Card 2, Full sample (out-of-time, no trim)

Every arms-length sale, including the cash and distressed tail. This is what a
homeowner actually experiences, and nobody passes it.

| Statistic | Target | OPA | Our model |
|---|---|---|---|
| Median ratio | 0.90–1.10 | 0.983 ✓ | 0.975 ✓ |
| COD | ≤ 15 | 34.5 ✗ | 25.9 ✗ |
| PRD | 0.98–1.03 | 1.190 ✗ | 1.071 ✗ |
| PRB | ±0.05 | −0.234 ✗ | −0.060 ✗ |
| MAPE |, | 34.0% | 25.4% |

On the full sample the model is still mildly regressive and above the uniformity
target, but a **fraction** of OPA's regressivity (PRB −0.06 vs −0.23, roughly a
quarter; PRD 1.07 vs 1.19) and much tighter dispersion (COD 25.9 vs 34.5).

## The honest reading

1. **The gap between the two cards is the whole story.** Going from full to
   IAAO-standard drops the model's COD 25.9 → 17.0 and its PRB −0.06 → −0.02. That
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
