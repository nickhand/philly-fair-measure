export interface AnnualReportNarrativeInput {
  tax_year: number
  status: string
  correction: { net_corrective_pp: number }
  vertical_equity: {
    verdict: string
    standard_metrics_verdict: string
    tier_movement: {
      cheapest: string
      most_expensive: string
      larger_shift: string
    }
  }
  uniformity: { verdict: string }
  tiers: Array<{ new_ratio_pct: number }>
  benchmark_validation: { verdict: string }
  opa_study_verdict: string
}

export interface AnnualReportNarrative {
  statusLabel: string
  headline: string
  lead: string
  findingHeadline: string
  calloutLead: string
  callout: string
  benchmarkMethodsIntro: string
  standardMetricsIntro: string
  opaStudyIntro: string
}

function benchmarkSentence(verdict: string): string {
  if (verdict === 'model_less_regressive') {
    return 'Gold-standard fairness tests (PRD, PRB, and VEI) found our model less regressive than OPA, making it a useful independent benchmark—not ground truth.'
  }
  if (verdict === 'opa_less_regressive') {
    return 'Gold-standard fairness tests (PRD, PRB, and VEI) found OPA less regressive than our model. We still show our model as an independent check—not ground truth.'
  }
  if (verdict === 'tie') {
    return 'Gold-standard fairness tests (PRD, PRB, and VEI) found no clear regressivity difference between our model and OPA. We show our model as an independent check—not ground truth.'
  }
  return 'Gold-standard fairness tests (PRD, PRB, and VEI) gave mixed results when comparing our model with OPA. We show our model as an independent check—not ground truth.'
}

function movementPhrase(direction: string): string {
  if (direction === 'closer') return 'closer to that benchmark'
  if (direction === 'farther') return 'farther from that benchmark'
  return 'about the same distance from that benchmark'
}

function shiftSentence(largerShift: string): string {
  if (largerShift === 'cheapest') return 'The cheaper-home shift was larger.'
  if (largerShift === 'most_expensive') return 'The expensive-home shift was larger.'
  return 'The two shifts were about the same size.'
}

function standardMetricsSentence(verdict: string): string {
  if (verdict === 'worsened') return 'All three tests show that regressivity got worse.'
  if (verdict === 'improved') return 'All three tests show that regressivity improved.'
  if (verdict === 'unchanged') return 'All three tests show little change in regressivity.'
  return 'The three tests gave mixed results on regressivity.'
}

function correctionSentence(netCorrectivePp: number): string {
  if (Math.abs(netCorrectivePp) < 0.05) {
    return 'About as many homes moved closer to our estimate as moved farther away.'
  }
  const slightly = Math.abs(netCorrectivePp) < 5 ? 'Slightly more' : 'More'
  return netCorrectivePp > 0
    ? `${slightly} homes moved closer to our estimate than farther away.`
    : `${slightly} homes moved farther from our estimate than closer.`
}

function uniformitySentence(verdict: string): string {
  if (verdict === 'improved') return 'Overall consistency improved.'
  if (verdict === 'worsened') return 'Overall consistency worsened.'
  if (verdict === 'unchanged') return 'Overall consistency changed little.'
  return 'The consistency result was unavailable.'
}

function equitySentence(verdict: string): string {
  if (verdict === 'worsened') return 'The fairness gap by home value grew.'
  if (verdict === 'improved') return 'The fairness gap by home value shrank.'
  return 'The fairness gap by home value changed little.'
}

function benchmarkMethodsIntro(verdict: string): string {
  const base = 'On the same out-of-time financed-sales test'
  if (verdict === 'model_less_regressive') {
    return `${base}, our model was less regressive than OPA on all three vertical-equity measures`
  }
  if (verdict === 'opa_less_regressive') {
    return `${base}, OPA was less regressive than our model on all three vertical-equity measures`
  }
  if (verdict === 'tie') {
    return `${base}, the measures found no clear regressivity difference between our model and OPA`
  }
  return `${base}, the measures did not all favor the same benchmark`
}

function standardMetricsIntro(verdict: string): string {
  if (verdict === 'worsened') return 'All three standard vertical-equity measures worsened'
  if (verdict === 'improved') return 'All three standard vertical-equity measures improved'
  if (verdict === 'unchanged') return 'All three standard vertical-equity measures changed little'
  return 'The standard vertical-equity measures were mixed'
}

function opaStudyIntro(verdict: string, taxYear: number): string {
  if (verdict === 'within_recommended_ranges') {
    return `OPA’s own and outside sales studies found its citywide ${taxYear} measures within recommended ranges.`
  }
  if (verdict === 'outside_recommended_ranges') {
    return `OPA’s own and outside sales studies found its citywide ${taxYear} measures outside recommended ranges.`
  }
  return `OPA’s own and outside sales studies gave mixed results for its citywide ${taxYear} measures.`
}

export function annualReportNarrative(report: AnnualReportNarrativeInput): AnnualReportNarrative {
  const equity = report.vertical_equity
  const cheapest = report.tiers[0]
  const currentPattern =
    equity.tier_movement.cheapest === 'farther' &&
    equity.tier_movement.most_expensive === 'closer' &&
    cheapest != null &&
    cheapest.new_ratio_pct > 100

  const headline =
    equity.verdict === 'worsened'
      ? `The ${report.tax_year} update widened the fairness gap by home value.`
      : equity.verdict === 'improved'
        ? `The ${report.tax_year} update narrowed the fairness gap by home value.`
        : `The ${report.tax_year} update left the fairness gap by home value about the same.`

  const movement = `The new ${report.tax_year} reassessment moved cheaper homes ${movementPhrase(equity.tier_movement.cheapest)} while moving more expensive homes ${movementPhrase(equity.tier_movement.most_expensive)}.`
  const lead = [
    benchmarkSentence(report.benchmark_validation.verdict),
    movement,
    shiftSentence(equity.tier_movement.larger_shift),
    standardMetricsSentence(equity.standard_metrics_verdict),
  ].join(' ')

  return {
    statusLabel: report.status === 'provisional' ? 'Early check' : 'Final report',
    headline,
    lead,
    findingHeadline: currentPattern
      ? 'The cheaper the home, the farther above our estimate.'
      : `How the ${report.tax_year} reassessment changed five home-value groups.`,
    calloutLead: 'The measures answer different questions.',
    callout: [
      correctionSentence(report.correction.net_corrective_pp),
      uniformitySentence(report.uniformity.verdict),
      equitySentence(equity.verdict),
    ].join(' '),
    benchmarkMethodsIntro: benchmarkMethodsIntro(report.benchmark_validation.verdict),
    standardMetricsIntro: standardMetricsIntro(equity.standard_metrics_verdict),
    opaStudyIntro: opaStudyIntro(report.opa_study_verdict, report.tax_year),
  }
}
