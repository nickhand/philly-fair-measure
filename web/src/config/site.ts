/** Site-wide links and credits, in one place. */

export const SITE = {
  creatorName: 'Nick Hand',
  creatorUrl: 'https://nickhand.dev',
  // TODO: update once the repository is published under its public name.
  githubUrl: 'https://github.com/nickhand/philly-assessments',
  modelDocsUrl: 'https://github.com/nickhand/philly-assessments/blob/main/docs/model.md',
} as const

/** The city's own record of what it has on file for a property — the page an
 * owner should check when a recorded fact looks wrong. */
export function opaInquiryUrl(parcelId: string): string {
  return `https://opainquiry.phila.gov/opa.apps/help/PropInq.aspx?acct_num=${encodeURIComponent(parcelId)}`
}
