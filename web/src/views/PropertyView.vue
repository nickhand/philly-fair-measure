<script setup lang="ts">
/** The heart of the site: one home's full assessment analysis.
 * Loads the fast core first (verdict renders immediately), then the heavier
 * report (drivers/equity/history) fills in progressively.
 *
 * DESIGN PASS (handoff SFC): all copy, data flow, ARIA and <details> fallbacks
 * preserved. Verdict-card anatomy (top bar, icon chip, serif headline,
 * computed delta pill) per the mocks. Local additions kept on top of the
 * handoff version: `.print-compact` + `data-url` (print.css contract), the
 * error-state retry button, and the print button. */
import { computed, ref, watch } from 'vue'
import { api, ApiError } from '@/api/client'
import type { PropertyCore, Report } from '@/api/types'
import { money, num, pct } from '@/utils/format'
import { opaInquiryUrl, SITE } from '@/config/site'
import { track } from '@/lib/analytics'
import type { CompRow } from '@/api/types'
import { verdictFor } from '@/utils/verdict'
import IntervalStrip from '@/components/viz/IntervalStrip.vue'
import DriverBars from '@/components/viz/DriverBars.vue'
import PeerHistogram from '@/components/viz/PeerHistogram.vue'
import HistorySpark from '@/components/viz/HistorySpark.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import InfoTip from '@/components/ui/InfoTip.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'

const props = defineProps<{ parcelId: string }>()

const core = ref<PropertyCore | null>(null)
const report = ref<Report | null>(null)
const coreError = ref<string | null>(null)
const reportLoading = ref(false)
/** Comparable sales — loaded on demand (the endpoint recomputes model comps
 * and takes a few seconds; no reason to pay that on every page view). */
const comps = ref<CompRow[] | null>(null)
const compsLoading = ref(false)
const compsError = ref(false)

async function load(id: string) {
  core.value = null
  report.value = null
  coreError.value = null
  comps.value = null
  compsError.value = false
  try {
    core.value = await api.property(id)
  } catch (err) {
    coreError.value =
      err instanceof ApiError && err.status === 404
        ? 'We could not find that property. Try searching again from the home page.'
        : 'Something went wrong loading this property. Please try again.'
    return
  }
  track('report_viewed', { flag: core.value.flag, family: core.value.model_family })
  reportLoading.value = true
  try {
    report.value = await api.report(id)
  } catch {
    report.value = null // panels degrade individually below
  } finally {
    reportLoading.value = false
  }
}

watch(() => props.parcelId, load, { immediate: true })

const verdict = computed(() => (core.value ? verdictFor(core.value.flag) : null))
const hasInterval = computed(
  () =>
    core.value != null &&
    core.value.model_pi_low_90 != null &&
    core.value.model_pi_high_90 != null &&
    core.value.model_median != null &&
    core.value.opa_market_value != null,
)

/** Delta pill: computed dollar gap (data, not verdict copy). */
const deltaPill = computed(() => {
  if (!core.value || !hasInterval.value) return null
  const { flag, opa_market_value: opa, model_pi_low_90: low, model_pi_high_90: high } = core.value
  if (flag === 'over_assessed_candidate') return `${money(opa! - high!)} above our highest estimate`
  if (flag === 'under_assessed_candidate') return `${money(low! - opa!)} below our lowest estimate`
  if (flag === 'within_range') return 'Inside our 90% range'
  return null
})

const signalChips = computed(() => {
  const s = core.value?.signals
  if (!s) return []
  const chips: string[] = []
  if (s.aerial_change) chips.push('Aerial photos show recent physical change')
  if ((s.vacancy_complaints_5y ?? 0) > 0)
    chips.push(`${s.vacancy_complaints_5y} vacancy complaint(s) in 5 years`)
  if ((s.unpermitted_work_complaints_5y ?? 0) > 0)
    chips.push(`${s.unpermitted_work_complaints_5y} unpermitted-work complaint(s)`)
  if (s.tax_delinquent) chips.push('Property tax balance owed')
  if (s.rental_license) chips.push('Has a rental license')
  if ((s.linked_parcels ?? 0) > 1) chips.push('Owner holds a neighboring lot')
  return chips
})

const cityLink = computed(() =>
  core.value ? `https://property.phila.gov/?p=${core.value.parcel_id}` : '#',
)
const inquiryLink = computed(() =>
  core.value ? opaInquiryUrl(core.value.parcel_id) : '#',
)


async function loadComps() {
  track('comps_shown')
  compsLoading.value = true
  compsError.value = false
  try {
    comps.value = await api.comps(props.parcelId)
  } catch {
    compsError.value = true
  } finally {
    compsLoading.value = false
  }
}

function distMiles(m: number | null): string {
  if (m == null) return '—'
  const ft = m * 3.28084
  return ft < 900 ? `${Math.round(ft / 10) * 10} ft` : `${(m / 1609.34).toFixed(1)} mi`
}
const liveUrl = computed(() => (typeof window === 'undefined' ? '' : window.location.href))

function printPage() {
  track('report_printed')
  window.print()
}
</script>

<template>
  <div
    class="report-root print-compact mx-auto max-w-5xl px-4 py-6 sm:py-8"
    :data-parcel-id="core?.parcel_id"
    :data-updated="report?.screen_built"
    :data-url="liveUrl"
  >
    <RouterLink to="/" class="no-print text-body-sm font-semibold text-brand-600">← New search</RouterLink>

    <!-- error -->
    <div v-if="coreError" class="mt-6 rounded-xl border border-[#f2c9ae] bg-white p-6 text-center">
      <div class="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-over-soft">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c2410c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 21.5 20h-19Z" /><line x1="12" y1="9.5" x2="12" y2="14" /><circle cx="12" cy="17" r="0.5" fill="#c2410c" /></svg>
      </div>
      <h1 class="mt-3 text-base font-bold text-ink">{{ coreError }}</h1>
      <button
        type="button"
        class="mt-4 min-h-11 rounded-md bg-brand-600 px-5 font-bold text-white hover:bg-brand-700"
        @click="load(props.parcelId)"
      >
        Try again
      </button>
    </div>

    <!-- loading core -->
    <div v-else-if="!core" class="mt-6"><SkeletonBlock /></div>

    <template v-else>
      <!-- header + verdict -->
      <div class="mt-4">
        <h1 class="text-2xl font-extrabold tracking-tight text-ink sm:text-3xl">{{ core.address }}</h1>
        <p class="mt-1 text-body-sm text-muted">
          Philadelphia · OPA #{{ core.parcel_id }} ·
          <a :href="cityLink" rel="noopener" class="font-semibold text-brand-600 underline"
            >city record</a
          >
        </p>
      </div>

      <div
        v-if="verdict"
        class="verdict-card mt-5 overflow-hidden rounded-xl border border-line-soft bg-white shadow-verdict sm:rounded-[14px]"
      >
        <div class="h-1.5" :style="{ background: verdict.hex }" aria-hidden="true"></div>
        <div class="p-5 sm:p-6">
          <div class="flex items-start gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
              :class="verdict.badgeClass"
              aria-hidden="true"
            >
              <!-- icon per flag -->
              <svg v-if="core.flag === 'over_assessed_candidate'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 21.5 20h-19Z" /><line x1="12" y1="9.5" x2="12" y2="14" /><circle cx="12" cy="17" r="0.5" fill="currentColor" /></svg>
              <svg v-else-if="core.flag === 'within_range'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 12.5 10 18 19.5 7" /></svg>
              <svg v-else-if="core.flag === 'under_assessed_candidate'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="4" x2="12" y2="19" /><path d="M6 13l6 6 6-6" /></svg>
              <svg v-else width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><line x1="8" y1="12" x2="16" y2="12" /></svg>
            </div>
            <div>
              <h2 class="font-display text-2xl font-bold leading-tight text-ink sm:text-3xl" style="text-wrap: pretty">
                {{ verdict.headline }}
              </h2>
              <p
                v-if="deltaPill"
                class="mt-2 inline-block rounded-full px-2.5 py-0.5 text-caption font-bold tabular-nums"
                :class="verdict.badgeClass"
              >
                {{ deltaPill }}
              </p>
            </div>
          </div>
          <p class="mt-3.5 max-w-2xl text-base leading-relaxed text-body">{{ verdict.detail }}</p>

          <!-- the two numbers, as numbers (Tufte: show the data) — they also
               survive printing and screen readers without the chart -->
          <dl class="mt-4 flex flex-wrap items-end gap-x-8 gap-y-2">
            <div>
              <dt class="text-caption text-muted">City’s value · Tax Year {{ SITE.assessmentTaxYear }}</dt>
              <dd class="money text-2xl font-extrabold tracking-tight" :class="verdict.textClass">
                {{ money(core.opa_market_value) }}
              </dd>
            </div>
            <div>
              <dt class="text-caption text-muted">Our estimate</dt>
              <dd class="money text-2xl font-extrabold tracking-tight text-brand-600">
                {{ money(core.model_median) }}
              </dd>
            </div>
          </dl>

          <div v-if="hasInterval" class="mt-4">
            <IntervalStrip
              :low="core.model_pi_low_90!"
              :high="core.model_pi_high_90!"
              :median="core.model_median!"
              :opa="core.opa_market_value!"
              :flag="core.flag"
            />
            <div class="no-print">
              <InfoTip label="Why a range and not one number?">
                No one knows a home’s exact value until it sells. Our model studies thousands of nearby
                sales and gives its best estimate, plus a range it is 90% sure about — like a weather
                forecast for your home’s value.
                <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
                  >Learn how this works</RouterLink
                >.
              </InfoTip>
            </div>
          </div>

          <div class="mt-3.5 flex gap-2.5 rounded-md border border-gold-tint-border bg-gold-tint px-3.5 py-3">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8a6100" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="mt-0.5 shrink-0"><line x1="4" y1="12" x2="19" y2="12" /><path d="M13 6l6 6-6 6" /></svg>
            <p class="text-body-sm font-semibold leading-normal text-body">{{ verdict.nextStep }}</p>
          </div>
        </div>
      </div>

      <!-- report panels -->
      <div class="mt-6 grid gap-5 lg:grid-cols-2">
        <!-- drivers -->
        <SectionCard
          title="What shapes our estimate"
          subtitle="The biggest things pushing this home’s estimated value up or down, compared with a typical Philadelphia home."
        >
          <SkeletonBlock v-if="reportLoading" />
          <template v-else-if="report?.drivers">
            <DriverBars :drivers="report.drivers.drivers" />
            <div class="no-print">
              <InfoTip>
                Our model starts from a typical home (about
                {{ money(report.drivers.base_value) }}) and adjusts for this home’s facts — size,
                location, condition signals, and recent sales nearby. These bars show the largest
                adjustments. They explain the estimate; they do not judge whether the city’s value is
                fair.
              </InfoTip>
            </div>
          </template>
          <p v-else class="text-body-sm text-muted">
            We can’t break down the estimate for this property type yet.
          </p>
        </SectionCard>

        <!-- equity -->
        <SectionCard
          title="How your assessment compares nearby"
          subtitle="Equal treatment check: your assessment level next to similar homes in your area."
        >
          <SkeletonBlock v-if="reportLoading" />
          <template v-else-if="report?.equity">
            <PeerHistogram
              :histogram="report.equity.histogram"
              :you="report.equity.ratio"
              :peer-median="report.equity.peer_median_ratio"
            />
            <p class="mt-3 text-body-sm leading-relaxed text-body">
              This home is assessed at <strong class="text-ink">{{ pct(report.equity.ratio) }}</strong> of our
              estimated value. The middle for {{ num(report.equity.peer_n) }} similar homes
              ({{ report.equity.peer_label }}) is
              <strong class="text-ink">{{ pct(report.equity.peer_median_ratio) }}</strong
              >. It sits above {{ pct(report.equity.percentile / 100) }} of them.
            </p>
            <div class="no-print">
              <InfoTip>
                100% means the city’s value equals our estimate. Being above your neighbors does not
                prove the assessment is unfair — but a big gap is a reason to look closer.
              </InfoTip>
            </div>
          </template>
          <p v-else class="text-body-sm text-muted">
            Not enough similar homes nearby for a reliable comparison.
          </p>
        </SectionCard>

        <!-- history -->
        <SectionCard
          class="history-panel"
          title="Assessment history"
          subtitle="How the city’s value for this home changed over time, with actual sales marked."
        >
          <SkeletonBlock v-if="reportLoading" />
          <template v-else-if="report && report.assessment_history.length > 1">
            <HistorySpark
              :assessments="report.assessment_history"
              :sales="report.sale_history"
            />
            <details v-if="report.sale_history.length" class="mt-3 text-body-sm">
              <summary class="cursor-pointer font-medium text-brand-600">Recorded sales</summary>
              <ul class="mt-2 space-y-1 text-body">
                <li v-for="s in report.sale_history" :key="s.date + (s.price ?? 0)">
                  {{ s.date }} — {{ money(s.price) }}
                  <span v-if="s.validity && s.validity !== 'arms_length'" class="text-muted">
                    (not a regular market sale)
                  </span>
                </li>
              </ul>
            </details>
          </template>
          <p v-else class="text-body-sm text-muted">No assessment history available.</p>
        </SectionCard>

        <!-- signals + uniformity -->
        <SectionCard
          class="signals-panel"
          title="Other things we see in city data"
          subtitle="Neutral signals from public records. They add context; none of them is a judgment."
        >
          <ul v-if="signalChips.length" class="flex flex-wrap gap-2">
            <li
              v-for="chip in signalChips"
              :key="chip"
              class="rounded-full bg-chip px-3 py-1.5 text-caption font-semibold text-body"
            >
              {{ chip }}
            </li>
          </ul>
          <p v-else class="text-body-sm text-muted">Nothing notable in the public records we track.</p>

          <div v-if="core.twin_n && core.twin_ratio" class="mt-4 rounded-md border border-gold-border bg-gold-soft p-3.5">
            <div class="flex items-start gap-2.5">
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#8a6100" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="mt-0.5 shrink-0"><line x1="12" y1="3" x2="12" y2="21" /><line x1="4" y1="6" x2="20" y2="6" /><path d="M6 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><path d="M18 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><line x1="8" y1="21" x2="16" y2="21" /></svg>
              <div>
                <h3 class="text-body-sm font-bold text-gold-700">Identical homes on your block</h3>
                <p class="mt-1 text-caption leading-relaxed text-[#4d4633]">
                  City records show <strong>{{ core.twin_n }}</strong> homes identical to this one in
                  every recorded way. This home’s assessment is
                  <strong>{{ pct(core.twin_ratio - 1, 1) }}</strong>
                  {{ core.twin_ratio >= 1 ? 'above' : 'below' }} their middle value.
                </p>
                <p class="mt-1.5 text-caption leading-relaxed text-[#6d6242]">
                  Pennsylvania’s constitution requires uniform taxation: identical homes should get the
                  same assessment. A big gap against identical neighbors is strong appeal evidence.
                </p>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      <!-- comparable sales: the market evidence behind the estimate -->
      <SectionCard
        class="mt-6"
        title="Comparable sales nearby"
        subtitle="Recent arms-length sales of homes the model considers most similar — the market evidence behind the estimate."
      >
        <div v-if="comps === null && !compsLoading" class="no-print">
          <button
            type="button"
            class="min-h-11 rounded-md border border-line bg-white px-4 text-body-sm font-bold text-body hover:bg-paper"
            :disabled="compsLoading"
            @click="loadComps"
          >
            Show comparable sales
          </button>
          <p class="mt-1.5 text-caption text-faint">Takes a few seconds to compute.</p>
        </div>
        <SkeletonBlock v-else-if="compsLoading" />
        <p v-else-if="compsError" class="text-body-sm text-over" role="alert">
          Could not load comparable sales right now.
          <button type="button" class="font-bold underline" @click="loadComps">Try again</button>
        </p>
        <template v-else-if="comps && comps.length">
          <div class="overflow-x-auto">
            <table class="w-full text-left text-body-sm">
              <caption class="sr-only">Comparable sales the model used near this home</caption>
              <thead>
                <tr class="border-b border-line text-muted">
                  <th scope="col" class="py-2 pr-3 font-semibold">Address</th>
                  <th scope="col" class="py-2 pr-3 font-semibold">Sold</th>
                  <th scope="col" class="py-2 pr-3 text-right font-semibold">Price</th>
                  <th scope="col" class="py-2 pr-3 text-right font-semibold">In today’s market</th>
                  <th scope="col" class="py-2 pr-3 text-right font-semibold">Size</th>
                  <th scope="col" class="py-2 text-right font-semibold">Away</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in comps" :key="c.address + c.sale_date" class="border-b border-line-faint">
                  <th scope="row" class="py-2 pr-3 font-normal text-body">{{ c.address }}</th>
                  <td class="py-2 pr-3 whitespace-nowrap">{{ c.sale_date }}</td>
                  <td class="money py-2 pr-3 text-right">{{ money(c.sale_price) }}</td>
                  <td class="money py-2 pr-3 text-right font-semibold text-ink">
                    {{ money(c.price_adj_today) }}
                  </td>
                  <td class="money py-2 pr-3 text-right whitespace-nowrap">
                    {{ c.livable_area ? `${num(c.livable_area)} sq ft` : '—' }}
                  </td>
                  <td class="money py-2 text-right whitespace-nowrap">{{ distMiles(c.distance_m) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-2 text-caption text-faint">
            “In today’s market” adjusts each sale to current prices using our district price index.
            These are the model’s comparables, not an appraiser’s. You can bring your own comparables
            to an appeal.
          </p>
        </template>
        <p v-else class="text-body-sm text-muted">
          No comparable sales available for this property type.
        </p>
      </SectionCard>

      <!-- appeal on-ramp -->
      <SectionCard
        class="mt-6"
        title="Check your facts, then decide"
        subtitle="The city’s estimate rests on the facts it has on file. Wrong facts are the easiest thing to fix."
      >
        <template v-if="report?.drivers?.appeal_facts?.length">
          <table class="w-full text-left text-body-sm">
            <caption class="sr-only">Recorded facts about this home and their effect on value</caption>
            <thead>
              <tr class="border-b border-line text-muted">
                <th scope="col" class="py-2 pr-3 font-semibold">Fact on file</th>
                <th scope="col" class="py-2 pr-3 font-semibold">Recorded as</th>
                <th scope="col" class="py-2 text-right font-semibold">Effect on estimate</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="f in report.drivers.appeal_facts"
                :key="f.label"
                class="border-b border-line-faint"
                :class="f.implausible ? 'bg-over-row' : ''"
              >
                <th scope="row" class="py-2 pr-3 font-normal text-body">
                  {{ f.label }}
                  <svg
                    v-if="f.implausible"
                    width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#c2410c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"
                    role="img" aria-label="Looks unusual — double-check this one"
                    class="-mt-0.5 ml-0.5 inline-block"
                  ><path d="M12 3.5 21.5 20h-19Z" /><line x1="12" y1="10" x2="12" y2="14" /><circle cx="12" cy="17" r="0.5" fill="#c2410c" /></svg>
                </th>
                <td class="py-2 pr-3" :class="f.missing ? 'italic text-muted' : 'text-body'">
                  {{ f.recorded }}
                </td>
                <td class="py-2 text-right font-semibold tabular-nums text-ink">
                  {{ f.dollars >= 0 ? '+' : '−' }}{{ money(Math.abs(f.dollars)) }}
                </td>
              </tr>
            </tbody>
          </table>
          <p
            v-if="report.drivers.appeal_facts.some((f) => f.missing)"
            class="mt-2 text-caption text-faint"
          >
            “Not on file” means the city has no value recorded, so our model used a typical value
            instead — that stand-in is what the dollar effect reflects. Getting a missing fact
            onto the record can change the estimate.
          </p>
          <p class="mt-2 text-caption text-faint">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#c2410c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="-mt-0.5 inline-block"><path d="M12 3.5 21.5 20h-19Z" /><line x1="12" y1="10" x2="12" y2="14" /><circle cx="12" cy="17" r="0.5" fill="#c2410c" /></svg>
            = this recorded value looks unusual for Philadelphia homes — double-check it.
          </p>
        </template>
        <p v-else class="text-body-sm text-muted">
          Compare the city’s recorded facts (size, condition, year built) with reality at
          <a :href="cityLink" rel="noopener" class="font-semibold text-brand-600 underline"
            >property.phila.gov</a
          >; report anything wrong through the
          <a :href="inquiryLink" rel="noopener" class="font-semibold text-brand-600 underline"
            >property inquiry page</a
          >.
        </p>

        <div class="mt-5 rounded-lg bg-brand-50 p-4 text-body-sm text-[#2c3a4d]">
          <h3 class="text-body-sm font-extrabold text-brand-900">How to act on this (all free)</h3>
          <ol class="mt-2 list-decimal space-y-1.5 pl-5">
            <li>
              Check the facts on your record at
              <a :href="cityLink" rel="noopener" class="font-bold text-brand-600 underline"
                >property.phila.gov</a
              >.
            </li>
            <li>
              A fact is wrong? Tell OPA through the
              <a :href="inquiryLink" rel="noopener" class="font-bold text-brand-600 underline"
                >property inquiry page</a
              >.
            </li>
            <li>
              Disagree with the value itself? Ask OPA for a
              <a :href="SITE.flrUrl" rel="noopener" class="font-bold text-brand-600 underline"
                >First Level Review (FLR)</a
              >
              — the form comes in the mail with your new assessment notice, or you can request one
              from OPA.
            </li>
            <li>
              Still disagree after the review? File a formal appeal with the
              <strong>Board of Revision of Taxes (BRT)</strong> — the deadline is the first Monday
              of October each year.
            </li>
            <li>Bring this page, photos, and any repair estimates as evidence.</li>
          </ol>
          <p class="no-print mt-3">
            Details:
            <a
              href="https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/"
              rel="noopener"
              class="font-bold text-brand-600 underline"
              >phila.gov: appeal a property assessment</a
            >
          </p>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p class="text-caption leading-relaxed text-faint">
            This report is public information, not legal or appraisal advice. Estimates come from a
            statistical model and can be wrong for any single home — that’s why we show the range and
            the facts, not just a number.
            <span v-if="report?.screen_built">Data updated {{ report.screen_built }}.</span>
          </p>
          <button
            type="button"
            class="no-print inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md border border-line bg-white px-4 text-body-sm font-bold text-body hover:bg-paper"
            @click="printPage"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9V3h12v6" /><path d="M6 18H4.5A1.5 1.5 0 0 1 3 16.5v-5A1.5 1.5 0 0 1 4.5 10h15a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H18" /><rect x="6" y="14" width="12" height="7" rx="0.5" /></svg>
            Print this report
          </button>
        </div>
      </SectionCard>
    </template>
  </div>
</template>
