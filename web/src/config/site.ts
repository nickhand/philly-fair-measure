/** Site-wide links and credits, in one place. */
import stats from '@/data/siteStats.json'

function formatCycleDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export const SITE = {
  creatorName: 'Nick Hand',
  creatorUrl: 'https://nickhand.dev',
  githubUrl: 'https://github.com/nickhand/philly-fair-measure',
  modelDocsUrl: 'https://github.com/nickhand/philly-fair-measure/blob/main/docs/model.md',
  /** OPA's First Level Review — the form arrives by mail with each new
   * assessment notice, or owners can request one. */
  flrUrl:
    'https://www.phila.gov/departments/office-of-property-assessment/property-assessments/#first-level-review-flr',
  /** The Board of Revision of Taxes formal-appeal forms and documents. */
  appealFormsUrl: 'https://www.phila.gov/documents/property-assessment-appeal-documents-and-forms/',
  propertyTaxReliefUrl:
    'https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/',
  /** Compatibility names used across the appeal flow; all come from the
   * generated annual-report contract rather than hand-entered frontend data. */
  assessmentTaxYear: stats.annual_report.tax_year,
  flrDeadlineText: formatCycleDate(stats.annual_report.appeal_deadlines.first_level_review),
  appealDeadlineText: formatCycleDate(stats.annual_report.appeal_deadlines.formal_appeal),
} as const

/** The city's public record for a property — where an owner reviews the facts
 * on file (size, condition, year built) that drive the assessment. */
export function cityPropertyUrl(parcelId: string): string {
  return `https://property.phila.gov/?p=${encodeURIComponent(parcelId)}`
}

/** The city's own record of what it has on file for a property — the page an
 * owner should check when a recorded fact looks wrong. With no account number
 * it opens the inquiry landing, where the owner can search for themselves. */
export function opaInquiryUrl(parcelId?: string | null): string {
  const base = 'https://opainquiry.phila.gov/opa.apps/help/PropInq.aspx'
  return parcelId ? `${base}?acct_num=${encodeURIComponent(parcelId)}` : base
}
