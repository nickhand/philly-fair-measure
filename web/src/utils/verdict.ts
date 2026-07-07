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

import type { Attention, Flag } from '@/api/types'

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
    headline: 'Your assessment is inside our range',
    detail:
      "The city's value sits comfortably inside the range of prices this home could realistically sell for. Our range is wide on purpose — no model can pin down a home's exact value — so this means we see no sign of a problem, not that the number is perfect.",
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
  insufficient_record: {
    flag: 'insufficient_record',
    headline: 'The city’s record here is incomplete',
    detail:
      'The city has not recorded basic facts for this home — like its living area — so no model can fairly check its value. This usually means brand-new construction the city is still writing up.',
    nextStep:
      'Check what the city has on file for this address. Once the record is complete, we can check it.',
    textClass: 'text-fair',
    badgeClass: 'bg-fair-soft text-fair',
    hex: '#8593a4',
  },
}

/** Watch tier: the city's value sits in the shown band's outer tenth, on the
 * far side of the shown estimate (computed server-side from the display band,
 * so this copy is true of the chart drawn next to it). Deliberately weaker
 * language than a flag — "worth a look", never "may be wrong" — with tinted
 * (not full-strength) versions of the over/under hexes. */
export const WATCH_VERDICTS: Record<'high' | 'low', Verdict> = {
  high: {
    flag: 'within_range',
    headline: 'Your assessment sits near the top of our range',
    detail:
      "The city's value is still inside the range of prices this home could sell for, but close to its upper edge. That is not proof of a problem — it is a reason to look closer.",
    nextStep:
      'Check the facts the city has on file below, and see how your assessment compares with similar homes. If a recorded fact is wrong, the fix is free.',
    textClass: 'text-over',
    badgeClass: 'bg-over-soft text-over',
    // deliberately much lighter than the flag hex — on the map the tiers must
    // separate at dot size (strong flags also render larger, with a stroke)
    hex: '#f5a869',
  },
  low: {
    flag: 'within_range',
    headline: 'Your assessment sits near the bottom of our range',
    detail:
      "The city's value is inside our range but close to its lower edge. A lower assessment usually means a lower tax bill.",
    nextStep: 'Most owners do not need to do anything with this information.',
    textClass: 'text-under',
    badgeClass: 'bg-under-soft text-under',
    hex: '#7ec3e8',
  },
}

/** Watch rows whose city value sits beyond the shown band entirely. These are
 * one-machine calls: a flag needs both checking methods to agree, and here
 * they don't (or the home is a new build, where the over call is withheld by
 * rule). The chart draws the marker outside the band, so the copy must say
 * "above/below", not "inside but near the edge". */
export const WATCH_BEYOND_VERDICTS: Record<'high' | 'low', Verdict> = {
  high: {
    ...WATCH_VERDICTS.high,
    headline: 'Your assessment is above our range',
    detail:
      "The city's value is higher than the top of the range shown here. We don't flag it, because our two ways of checking this home do not agree about it. That is not proof of a problem — it is a reason to look closer.",
  },
  low: {
    ...WATCH_VERDICTS.low,
    headline: 'Your assessment is below our range',
    detail:
      "The city's value is lower than the bottom of the range shown here. We don't flag it, because our two ways of checking this home do not agree about it. A lower assessment usually means a lower tax bill.",
  },
}

/** New builds get "above our range" for a different reason: both methods can
 * read the city's value as high, but the range itself likely runs low (it is
 * built from nearby sales of mostly older homes), so the over call is
 * withheld. The disagreement sentence would be false here. */
const WATCH_ABOVE_NEW_BUILD: Verdict = {
  ...WATCH_BEYOND_VERDICTS.high,
  detail:
    "The city's value is higher than the top of the range shown here. This home is newly built, and our range comes from nearby sales of mostly older homes, so it can run low. The note below explains.",
}

export interface VerdictContext {
  /** The numbers the page draws, so watch copy can tell "near the top of the
   * shown band" from "above it". Omit (map dots, legends) to get the in-band
   * wording — colors are identical either way. */
  cityValue?: number | null
  bandLo?: number | null
  bandHi?: number | null
  newBuild?: boolean
}

export function verdictFor(flag: Flag, attention: Attention = null, ctx: VerdictContext = {}): Verdict {
  if (flag === 'within_range' && attention) {
    const { cityValue, bandLo, bandHi, newBuild } = ctx
    if (attention === 'high' && cityValue != null && bandHi != null && cityValue > bandHi)
      return newBuild ? WATCH_ABOVE_NEW_BUILD : WATCH_BEYOND_VERDICTS.high
    if (attention === 'low' && cityValue != null && bandLo != null && cityValue < bandLo)
      return WATCH_BEYOND_VERDICTS.low
    return WATCH_VERDICTS[attention]
  }
  return VERDICTS[flag] ?? VERDICTS.no_assessment
}
