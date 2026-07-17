import { describe, expect, it } from 'vitest'
import {
  annualReportNarrative,
  type AnnualReportNarrativeInput,
} from '@/utils/annualReportNarrative'

const current: AnnualReportNarrativeInput = {
  tax_year: 2027,
  status: 'provisional',
  correction: { net_corrective_pp: 3.8 },
  vertical_equity: {
    verdict: 'worsened',
    standard_metrics_verdict: 'worsened',
    tier_movement: {
      cheapest: 'farther',
      most_expensive: 'closer',
      larger_shift: 'cheapest',
    },
  },
  uniformity: { verdict: 'improved' },
  tiers: [{ new_ratio_pct: 146.3 }, { new_ratio_pct: 91.0 }],
  benchmark_validation: { verdict: 'model_less_regressive' },
  opa_study_verdict: 'within_recommended_ranges',
}

describe('annualReportNarrative', () => {
  it('describes the exported 2027 directions', () => {
    const copy = annualReportNarrative(current)

    expect(copy.headline).toMatch(/widened/)
    expect(copy.lead).toMatch(/cheaper homes farther/)
    expect(copy.lead).toMatch(/more expensive homes closer/)
    expect(copy.lead).toMatch(/regressivity got worse/)
    expect(copy.statusLabel).toBe('Early check')
  })

  it('reverses the claims when the exported evidence reverses', () => {
    const reversed: AnnualReportNarrativeInput = {
      ...current,
      vertical_equity: {
        verdict: 'improved',
        standard_metrics_verdict: 'improved',
        tier_movement: {
          cheapest: 'closer',
          most_expensive: 'farther',
          larger_shift: 'most_expensive',
        },
      },
      uniformity: { verdict: 'worsened' },
      correction: { net_corrective_pp: -6.0 },
      tiers: [{ new_ratio_pct: 120 }, { new_ratio_pct: 80 }],
    }
    const copy = annualReportNarrative(reversed)

    expect(copy.headline).toMatch(/narrowed/)
    expect(copy.lead).toMatch(/cheaper homes closer/)
    expect(copy.lead).toMatch(/more expensive homes farther/)
    expect(copy.lead).toMatch(/regressivity improved/)
    expect(copy.callout).toMatch(/fairness gap by home value shrank/)
    expect(copy.headline).not.toMatch(/widened/)
    expect(copy.lead).not.toMatch(/got worse/)
  })
})
