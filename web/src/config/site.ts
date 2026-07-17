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
  /** The Board of Revision of Taxes formal-appeal forms and documents. */
  appealFormsUrl: 'https://www.phila.gov/documents/property-assessment-appeal-documents-and-forms/',
  propertyTaxReliefUrl:
    'https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/',
  ty2027ReleaseUrl:
    'https://www.phila.gov/2026-06-30-city-of-philadelphia-to-mail-2027-property-assessments-and-launch-expanded-outreach-to-connect-homeowners-to-tax-relief/',
  ty2027MethodologyUrl:
    'https://www.phila.gov/media/20260629163818/opa-tax-year-2027-mass-appraisal-valuation-methodology-summary.pdf',
  ty2027RatioStudiesUrl: 'https://www.phila.gov/documents/annual-ratio-studies/',
  ty2027NotebookUrl:
    'https://github.com/nickhand/philly-fair-measure/blob/main/notebooks/ty2027_report_reproduction.ipynb',
  iaaoRatioStudyUrl:
    'https://www.iaao.org/wp-content/uploads/2025_Ratio_Studies_Exposure_Draft.pdf',
  /** The assessment cycle currently shown. Update on each reassessment. */
  assessmentTaxYear: 2027,
  flrDeadlineText: 'September 1, 2026',
  appealDeadlineText: 'October 5, 2026',
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
