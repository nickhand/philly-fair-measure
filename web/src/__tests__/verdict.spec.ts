import { describe, expect, it } from 'vitest'
import { verdictFor, VERDICTS, WATCH_BEYOND_VERDICTS, WATCH_VERDICTS } from '@/utils/verdict'

describe('verdictFor', () => {
  it('maps every screen flag to plain-language copy', () => {
    expect(verdictFor('within_range').headline).toBe('Your assessment is inside our range')
    expect(verdictFor('over_assessed_candidate').headline).toBe(
      'Your assessment may be too high',
    )
    expect(verdictFor('under_assessed_candidate').headline).toBe(
      'Your assessment is lower than our estimate',
    )
  })

  it('never presents a candidate flag as a certainty', () => {
    // "may" language is a hard requirement — the flag is a possibility, not a verdict.
    expect(VERDICTS.over_assessed_candidate.headline).toMatch(/may/)
  })

  it('acknowledges the range is wide, not a fairness verdict', () => {
    // the 90% band spans roughly 0.4x-2.3x of the estimate; "inside" must not
    // read as "certified fair"
    expect(VERDICTS.within_range.detail).toMatch(/wide/)
  })

  it('returns the watch tier only for within-range rows with attention', () => {
    expect(verdictFor('within_range', 'high')).toBe(WATCH_VERDICTS.high)
    expect(verdictFor('within_range', 'low')).toBe(WATCH_VERDICTS.low)
    expect(verdictFor('within_range', null)).toBe(VERDICTS.within_range)
    // attention never upgrades or downgrades a real flag
    expect(verdictFor('over_assessed_candidate', 'high')).toBe(VERDICTS.over_assessed_candidate)
  })

  it('keeps watch-tier language weaker than a flag', () => {
    // "near the top/bottom" is a position statement, never a wrongness claim
    expect(WATCH_VERDICTS.high.headline).toMatch(/near the top/)
    expect(WATCH_VERDICTS.high.detail).toMatch(/not proof/)
    expect(WATCH_VERDICTS.low.headline).toMatch(/near the bottom/)
  })

  it('says "above/below our range" when the city value is beyond the shown band', () => {
    // the copy must match the drawn chart: "inside but near the edge" would
    // be false for a marker rendered outside the band
    const band = { bandLo: 288_000, bandHi: 918_000 }
    const above = verdictFor('within_range', 'high', { cityValue: 1_290_200, ...band })
    expect(above).toBe(WATCH_BEYOND_VERDICTS.high)
    expect(above.headline).toMatch(/above our range/)
    expect(above.detail).toMatch(/don't agree/)
    const below = verdictFor('within_range', 'low', { cityValue: 150_000, ...band })
    expect(below).toBe(WATCH_BEYOND_VERDICTS.low)
    expect(below.headline).toMatch(/below our range/)
    // in-band watch rows keep the near-the-edge wording
    expect(verdictFor('within_range', 'high', { cityValue: 900_000, ...band })).toBe(
      WATCH_VERDICTS.high,
    )
    // colors and next steps are shared: the tier is the same, only the
    // position statement changes
    expect(WATCH_BEYOND_VERDICTS.high.hex).toBe(WATCH_VERDICTS.high.hex)
    expect(WATCH_BEYOND_VERDICTS.high.nextStep).toBe(WATCH_VERDICTS.high.nextStep)
  })

  it('explains new-build above-range rows without the disagreement claim', () => {
    // for new builds both methods can read the value as high; the flag is
    // withheld by rule, so "our checks disagree" would be false
    const v = verdictFor('within_range', 'high', {
      cityValue: 1_290_200,
      bandLo: 288_000,
      bandHi: 918_000,
      newBuild: true,
    })
    expect(v.headline).toMatch(/above our range/)
    expect(v.detail).toMatch(/newly built/)
    expect(v.detail).not.toMatch(/don't agree/)
  })

  it('uses the colorblind-safe blue/orange pair', () => {
    // Flag & Ledger design pass: under shifted #1d4ed8 → #0369a1 (cyan-leaning)
    // so it can't be read as the brand azure. The blue/orange opposition —
    // the thing this test protects — is unchanged.
    expect(VERDICTS.over_assessed_candidate.hex).toBe('#c2410c')
    expect(VERDICTS.under_assessed_candidate.hex).toBe('#0369a1')
  })

  it('falls back safely for unknown flags', () => {
    expect(verdictFor('no_assessment').headline).toBe('No city value on record')
  })

  it('gives incomplete city records a no-verdict explanation, not a judgment', () => {
    const v = verdictFor('insufficient_record')
    expect(v.headline).toBe('The city’s record here is incomplete')
    expect(v.detail).toMatch(/brand-new construction/)
  })
})
