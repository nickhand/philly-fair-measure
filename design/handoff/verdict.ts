/** The single source of truth for verdict language and color.
 *
 * Copy rules: 8th-grade reading level, short sentences, no jargon, honest.
 * "Candidate" flags are possibilities, not conclusions — the words must say so.
 *
 * DESIGN PASS (Flag & Ledger): only hex values changed.
 * - under: #1d4ed8 → #0369a1 (cyan-leaning blue). Keeps the tested
 *   blue-vs-orange opposition (deutan/protan-safe) but no longer reads
 *   as the brand azure (#0f4d90).
 * - within_range: #334155 → #46545f (matches --color-fair token).
 * - no_assessment: #94a3b8 → #8593a4 (matches --color-none token).
 * All copy is UNCHANGED. Class strings are UNCHANGED (so existing test
 * assertions hold); the -soft/-text tokens give AA contrast as-is. If you
 * want the deeper badge text from the mocks (#9a3412 / #075985), add
 * text-over-text / text-under-text in the component templates instead.
 */

import type { Flag } from '@/api/types'

export interface Verdict {
  flag: Flag
  /** Short headline, e.g. shown next to the address. */
  headline: string
  /** One-or-two plain sentences under the headline. */
  detail: string
  /** What the owner might do next. */
  nextStep: string
  /** Tailwind classes keyed to the theme tokens (colorblind-safe pair). */
  textClass: string
  badgeClass: string
  /** Map/marker hex, must match the theme tokens in main.css. */
  hex: string
}

export const VERDICTS: Record<Flag, Verdict> = {
  within_range: {
    flag: 'within_range',
    headline: 'Your assessment looks fair',
    detail:
      "The city's value for this home is inside our estimate range. The two numbers tell a similar story.",
    nextStep:
      'No action needed. If the facts the city has about your home are wrong, you can still ask them to fix the records.',
    textClass: 'text-fair',
    badgeClass: 'bg-fair-soft text-fair',
    hex: '#46545f',
  },
  over_assessed_candidate: {
    flag: 'over_assessed_candidate',
    headline: 'Your assessment may be too high',
    detail:
      "The city's value is above the highest value our model finds likely for this home. That can mean a higher tax bill than the home's real value supports.",
    nextStep:
      'Check the facts below. If they support a lower value, you can appeal for free — see the steps at the end of this page.',
    textClass: 'text-over',
    badgeClass: 'bg-over-soft text-over',
    hex: '#c2410c',
  },
  under_assessed_candidate: {
    flag: 'under_assessed_candidate',
    headline: 'Your assessment is lower than our estimate',
    detail:
      "The city's value is below the lowest value our model finds likely. A lower assessment usually means a lower tax bill.",
    nextStep: 'Most owners do not need to do anything with this information.',
    textClass: 'text-under',
    badgeClass: 'bg-under-soft text-under',
    hex: '#0369a1',
  },
  no_assessment: {
    flag: 'no_assessment',
    headline: 'No city value on record',
    detail: 'We could not find a current city assessment for this property.',
    nextStep: 'Check the address on the city’s property site.',
    textClass: 'text-fair',
    badgeClass: 'bg-fair-soft text-fair',
    hex: '#8593a4',
  },
}

export function verdictFor(flag: Flag): Verdict {
  return VERDICTS[flag] ?? VERDICTS.no_assessment
}
