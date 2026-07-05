import { describe, expect, it } from 'vitest'
import { verdictFor, VERDICTS } from '@/utils/verdict'

describe('verdictFor', () => {
  it('maps every screen flag to plain-language copy', () => {
    expect(verdictFor('within_range').headline).toBe('Your assessment looks fair')
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
