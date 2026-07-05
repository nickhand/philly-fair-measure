import { describe, expect, it } from 'vitest'
import { verdictFor, VERDICTS, WATCH_VERDICTS } from '@/utils/verdict'

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
})
