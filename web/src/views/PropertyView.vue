<script setup lang="ts">
/** The heart of the site: one home's full assessment analysis.
 * Loads the fast core first (verdict renders immediately), then the heavier
 * report (drivers/equity/history) fills in progressively.
 *
 * Print: .report-root carries data-url/data-updated for the print provenance
 * footer; .no-print hides interactive furniture; .print-compact drops the
 * history/signals panels so the report fits one Letter page. */
import { computed, ref, watch } from 'vue'
import {
  ArrowDown,
  ArrowRight,
  Check,
  CircleMinus,
  ExternalLink,
  Printer,
  TriangleAlert,
} from 'lucide-vue-next'
import { api, ApiError } from '@/api/client'
import type { PropertyCore, Report } from '@/api/types'
import { money, num, pct } from '@/utils/format'
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

async function load(id: string) {
  core.value = null
  report.value = null
  coreError.value = null
  try {
    core.value = await api.property(id)
  } catch (err) {
    coreError.value =
      err instanceof ApiError && err.status === 404
        ? 'We could not find that property. Try searching again from the home page.'
        : 'Something went wrong loading this property. Please try again.'
    return
  }
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

/** Delta pill: the computed dollar gap between the city's value and the edge
 * of our range (never verdict copy — that stays centralized). */
const delta = computed(() => {
  const c = core.value
  if (!c || !hasInterval.value) return null
  if (c.flag === 'over_assessed_candidate') {
    return `${money((c.opa_market_value as number) - (c.model_pi_high_90 as number))} above our highest estimate`
  }
  if (c.flag === 'under_assessed_candidate') {
    return `${money((c.model_pi_low_90 as number) - (c.opa_market_value as number))} below our lowest estimate`
  }
  if (c.flag === 'within_range') return 'inside our estimate range'
  return null
})

const verdictIcon = computed(() => {
  switch (core.value?.flag) {
    case 'over_assessed_candidate':
      return TriangleAlert
    case 'under_assessed_candidate':
      return ArrowDown
    case 'within_range':
      return Check
    default:
      return CircleMinus
  }
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
const liveUrl = computed(() =>
  typeof window === 'undefined' ? '' : window.location.href,
)

function printPage() {
  window.print()
}
</script>

<template>
  <div
    class="report-root print-compact mx-auto max-w-5xl px-4 py-6 sm:py-8"
    :data-parcel-id="props.parcelId"
    :data-updated="report?.screen_built ?? '—'"
    :data-url="liveUrl"
  >
    <RouterLink to="/" class="no-print text-body-sm font-semibold text-brand-600"
      >← New search</RouterLink
    >

    <!-- error -->
    <div
      v-if="coreError"
      class="mt-6 rounded-lg border border-line-soft bg-white p-6"
    >
      <div class="flex items-start gap-3">
        <span
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-over-soft"
        >
          <TriangleAlert :size="20" class="text-over" aria-hidden="true" />
        </span>
        <div>
          <h1 class="text-title font-bold text-ink">{{ coreError }}</h1>
          <button
            type="button"
            class="mt-3 min-h-11 rounded-md bg-brand-600 px-5 font-bold text-white hover:bg-brand-700"
            @click="load(props.parcelId)"
          >
            Try again
          </button>
        </div>
      </div>
    </div>

    <!-- loading core -->
    <div v-else-if="!core" class="mt-6 rounded-lg border border-line-soft bg-white p-5">
      <SkeletonBlock />
    </div>

    <template v-else>
      <!-- header -->
      <div class="mt-4">
        <h1 class="text-h1 font-extrabold text-ink sm:text-[1.875rem]">{{ core.address }}</h1>
        <p class="mt-1 text-body-sm text-muted">
          Philadelphia · OPA #{{ core.parcel_id }} ·
          <a
            :href="cityLink"
            rel="noopener"
            class="inline-flex items-baseline gap-1 font-semibold text-brand-600 underline"
            >city record<ExternalLink :size="12" aria-hidden="true" class="self-center" /></a
          >
        </p>
      </div>

      <!-- verdict card: the headline moment -->
      <div
        v-if="verdict"
        class="verdict-card mt-5 overflow-hidden rounded-xl border border-line-soft bg-white shadow-verdict sm:rounded-[14px]"
      >
        <div class="h-1.5" :style="{ background: verdict.hex }" aria-hidden="true"></div>
        <div class="p-5 sm:p-6">
          <div class="flex items-center gap-3">
            <span
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
              :class="verdict.badgeClass"
              aria-hidden="true"
            >
              <component :is="verdictIcon" :size="20" />
            </span>
            <h2
              class="font-display text-verdict font-bold sm:text-verdict-lg"
              :class="verdict.textClass"
            >
              {{ verdict.headline }}
            </h2>
          </div>

          <p
            v-if="delta"
            class="money mt-3 inline-block rounded-full px-3 py-1 text-body-sm font-bold"
            :class="verdict.badgeClass"
          >
            {{ delta }}
          </p>

          <p class="mt-3 max-w-2xl text-body text-body">{{ verdict.detail }}</p>

          <div v-if="hasInterval" class="mt-5">
            <IntervalStrip
              :low="core.model_pi_low_90!"
              :high="core.model_pi_high_90!"
              :median="core.model_median!"
              :opa="core.opa_market_value!"
              :flag="core.flag"
            />
            <InfoTip class="no-print" label="Why a range and not one number?">
              No one knows a home’s exact value until it sells. Our model studies thousands of
              nearby sales and gives its best estimate, plus a range it is 90% sure about — like a
              weather forecast for your home’s value.
              <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
                >Learn how this works</RouterLink
              >.
            </InfoTip>
          </div>

          <div
            v-if="core.flag === 'over_assessed_candidate'"
            class="mt-4 flex items-start gap-2.5 rounded-md border border-gold-tint-border bg-gold-tint p-3"
          >
            <ArrowRight :size="16" class="mt-0.5 shrink-0 text-gold-700" aria-hidden="true" />
            <p class="text-body-sm font-semibold text-ink">{{ verdict.nextStep }}</p>
          </div>
          <p v-else class="mt-4 text-body-sm font-medium text-body">{{ verdict.nextStep }}</p>
        </div>
      </div>

      <!-- report panels -->
      <div class="mt-6 grid gap-6 lg:grid-cols-2">
        <!-- drivers -->
        <SectionCard
          title="What shapes our estimate"
          subtitle="The biggest things pushing this home’s estimated value up or down, compared with a typical Philadelphia home."
        >
          <SkeletonBlock v-if="reportLoading" />
          <template v-else-if="report?.drivers">
            <DriverBars :drivers="report.drivers.drivers" />
            <InfoTip class="no-print">
              Our model starts from a typical home (about
              {{ money(report.drivers.base_value) }}) and adjusts for this home’s facts — size,
              location, condition signals, and recent sales nearby. These bars show the largest
              adjustments. They explain the estimate; they do not judge whether the city’s value is
              fair.
            </InfoTip>
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
              :you-hex="verdict?.hex"
            />
            <p class="mt-3 text-body-sm text-body">
              This home is assessed at <strong>{{ pct(report.equity.ratio) }}</strong> of our
              estimated value. The middle for {{ num(report.equity.peer_n) }} similar homes
              ({{ report.equity.peer_label }}) is
              <strong>{{ pct(report.equity.peer_median_ratio) }}</strong
              >. It sits above {{ pct(report.equity.percentile / 100) }} of them.
            </p>
            <InfoTip class="no-print">
              100% means the city’s value equals our estimate. Being above your neighbors does not
              prove the assessment is unfair — but a big gap is a reason to look closer.
            </InfoTip>
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
              <summary class="cursor-pointer font-semibold text-brand-600">Recorded sales</summary>
              <ul class="mt-2 space-y-1 text-body">
                <li v-for="s in report.sale_history" :key="s.date + (s.price ?? 0)">
                  {{ s.date }} — <span class="money">{{ money(s.price) }}</span>
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
              class="rounded-full bg-chip px-3 py-1.5 text-body-sm text-body"
            >
              {{ chip }}
            </li>
          </ul>
          <p v-else class="text-body-sm text-muted">
            Nothing notable in the public records we track.
          </p>

          <div
            v-if="core.twin_n && core.twin_ratio"
            class="mt-4 rounded-md border border-gold-border bg-gold-soft p-3.5"
          >
            <h3 class="font-bold text-gold-700">Identical homes on your block</h3>
            <p class="mt-1 text-body-sm text-body">
              City records show <strong>{{ core.twin_n }}</strong> homes identical to this one in
              every recorded way. This home’s assessment is
              <strong>{{ pct(core.twin_ratio - 1, 1) }}</strong>
              {{ core.twin_ratio >= 1 ? 'above' : 'below' }} their middle value.
            </p>
            <p class="no-print mt-2 text-body-sm text-body">
              Pennsylvania’s constitution requires uniform taxation: identical homes should get the
              same assessment. A big gap against identical neighbors is strong appeal evidence.
            </p>
          </div>
        </SectionCard>
      </div>

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
                <th scope="col" class="py-2 pr-3 font-medium">Fact on file</th>
                <th scope="col" class="py-2 pr-3 font-medium">Recorded as</th>
                <th scope="col" class="py-2 font-medium">Effect on estimate</th>
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
                  <span
                    v-if="f.implausible"
                    class="inline-flex align-middle font-semibold text-over"
                    role="img"
                    aria-label="Looks unusual — double-check this one"
                  >
                    <TriangleAlert :size="14" aria-hidden="true" />
                  </span>
                </th>
                <td class="py-2 pr-3">{{ f.recorded }}</td>
                <td class="money py-2">
                  {{ f.dollars >= 0 ? '+' : '−' }}{{ money(Math.abs(f.dollars)) }}
                </td>
              </tr>
            </tbody>
          </table>
          <p class="mt-2 flex items-center gap-1.5 text-caption text-faint">
            <TriangleAlert :size="12" class="text-over" aria-hidden="true" />
            = this recorded value looks unusual for Philadelphia homes — double-check it.
          </p>
        </template>
        <p v-else class="text-body-sm text-muted">
          Compare the city’s recorded facts (size, condition, year built) with reality at
          <a :href="cityLink" rel="noopener" class="font-semibold text-brand-600 underline"
            >property.phila.gov</a
          >.
        </p>

        <div class="mt-5 rounded-md border border-gold-tint-border bg-gold-tint p-4 text-body-sm">
          <h3 class="font-bold text-ink">How to act on this (all free)</h3>
          <ol class="mt-2 list-decimal space-y-1.5 pl-5 text-body">
            <li>
              Wrong facts on file? Ask OPA for a review — this is called a
              <strong>First Level Review</strong> and takes one form.
            </li>
            <li>
              Think the value itself is too high? File an appeal with the
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
              class="font-semibold text-brand-600 underline"
              >phila.gov: appeal a property assessment</a
            >
          </p>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p class="text-caption text-faint">
            This report is public information, not legal or appraisal advice. Estimates come from a
            statistical model and can be wrong for any single home — that’s why we show the range
            and the facts, not just a number.
            <span v-if="report?.screen_built">Data updated {{ report.screen_built }}.</span>
          </p>
          <button
            type="button"
            class="no-print inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md border border-line bg-white px-4 text-body-sm font-bold text-body hover:bg-paper"
            @click="printPage"
          >
            <Printer :size="16" aria-hidden="true" /> Print this report
          </button>
        </div>
      </SectionCard>
    </template>
  </div>
</template>
