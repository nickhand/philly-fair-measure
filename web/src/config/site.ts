/** Site-wide links and credits, in one place. */

export const SITE = {
  creatorName: 'Nick Hand',
  creatorUrl: 'https://nickhand.dev',
  githubUrl: 'https://github.com/nickhand/philly-fair-measure',
  modelDocsUrl: 'https://github.com/nickhand/philly-fair-measure/blob/main/docs/model.md',
  /** OPA's First Level Review — the form arrives by mail with each new
   * assessment notice, or owners can request one. */
  flrUrl:
    'https://www.phila.gov/departments/office-of-property-assessment/property-assessments/#first-level-review-flr',
  /** The assessment cycle currently shown. Update on each reassessment. */
  assessmentTaxYear: 2027,
  flrDeadlineText: 'September 1',
  appealDeadlineText: 'the first Monday of October 2026',
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
