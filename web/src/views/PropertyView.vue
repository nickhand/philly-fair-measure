<script setup lang="ts">
/** The heart of the site: one home's full assessment analysis.
 * Loads the fast core first (verdict renders immediately), then the heavier
 * report (drivers/equity/history) fills in progressively. */
import { computed, ref, watch } from 'vue'
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

watch(
  () => props.parcelId,
  async (id) => {
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
  },
  { immediate: true },
)

const verdict = computed(() => (core.value ? verdictFor(core.value.flag) : null))
const hasInterval = computed(
  () =>
    core.value != null &&
    core.value.model_pi_low_90 != null &&
    core.value.model_pi_high_90 != null &&
    core.value.model_median != null &&
    core.value.opa_market_value != null,
)

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
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-6 sm:py-8">
    <RouterLink to="/" class="text-sm font-medium text-brand-600">← New search</RouterLink>

    <!-- error -->
    <div v-if="coreError" class="mt-6 rounded-2xl border border-over/30 bg-over-soft p-6">
      <h1 class="text-xl font-bold text-over">{{ coreError }}</h1>
    </div>

    <!-- loading core -->
    <div v-else-if="!core" class="mt-6"><SkeletonBlock /></div>

    <template v-else>
      <!-- header + verdict -->
      <div class="mt-4">
        <h1 class="text-2xl font-extrabold text-slate-900 sm:text-3xl">{{ core.address }}</h1>
        <p class="mt-1 text-sm text-slate-600">
          Philadelphia · OPA #{{ core.parcel_id }} ·
          <a :href="cityLink" rel="noopener" class="font-medium text-brand-600 underline"
            >city record</a
          >
        </p>
      </div>

      <div v-if="verdict" class="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <p
          class="inline-block rounded-full px-3 py-1 text-sm font-bold"
          :class="verdict.badgeClass"
        >
          {{ verdict.headline }}
        </p>
        <p class="mt-3 max-w-2xl text-slate-700">{{ verdict.detail }}</p>

        <div v-if="hasInterval" class="mt-6">
          <IntervalStrip
            :low="core.model_pi_low_90!"
            :high="core.model_pi_high_90!"
            :median="core.model_median!"
            :opa="core.opa_market_value!"
            :flag="core.flag"
          />
          <InfoTip label="Why a range and not one number?">
            No one knows a home’s exact value until it sells. Our model studies thousands of nearby
            sales and gives its best estimate, plus a range it is 90% sure about — like a weather
            forecast for your home’s value.
            <RouterLink to="/methodology" class="font-medium text-brand-600 underline"
              >Learn how this works</RouterLink
            >.
          </InfoTip>
        </div>

        <p class="mt-4 text-sm font-medium text-slate-800">{{ verdict.nextStep }}</p>
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
            <InfoTip>
              Our model starts from a typical home (about
              {{ money(report.drivers.base_value) }}) and adjusts for this home’s facts — size,
              location, condition signals, and recent sales nearby. These bars show the largest
              adjustments. They explain the estimate; they do not judge whether the city’s value is
              fair.
            </InfoTip>
          </template>
          <p v-else class="text-sm text-slate-600">
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
            <p class="mt-3 text-sm text-slate-700">
              This home is assessed at <strong>{{ pct(report.equity.ratio) }}</strong> of our
              estimated value. The middle for {{ num(report.equity.peer_n) }} similar homes
              ({{ report.equity.peer_label }}) is
              <strong>{{ pct(report.equity.peer_median_ratio) }}</strong
              >. It sits above {{ pct(report.equity.percentile / 100) }} of them.
            </p>
            <InfoTip>
              100% means the city’s value equals our estimate. Being above your neighbors does not
              prove the assessment is unfair — but a big gap is a reason to look closer.
            </InfoTip>
          </template>
          <p v-else class="text-sm text-slate-600">
            Not enough similar homes nearby for a reliable comparison.
          </p>
        </SectionCard>

        <!-- history -->
        <SectionCard
          title="Assessment history"
          subtitle="How the city’s value for this home changed over time, with actual sales marked."
        >
          <SkeletonBlock v-if="reportLoading" />
          <template v-else-if="report && report.assessment_history.length > 1">
            <HistorySpark
              :assessments="report.assessment_history"
              :sales="report.sale_history"
            />
            <details v-if="report.sale_history.length" class="mt-3 text-sm">
              <summary class="cursor-pointer font-medium text-brand-600">Recorded sales</summary>
              <ul class="mt-2 space-y-1 text-slate-700">
                <li v-for="s in report.sale_history" :key="s.date + (s.price ?? 0)">
                  {{ s.date }} — {{ money(s.price) }}
                  <span v-if="s.validity && s.validity !== 'arms_length'" class="text-slate-500">
                    (not a regular market sale)
                  </span>
                </li>
              </ul>
            </details>
          </template>
          <p v-else class="text-sm text-slate-600">No assessment history available.</p>
        </SectionCard>

        <!-- signals + uniformity -->
        <SectionCard
          title="Other things we see in city data"
          subtitle="Neutral signals from public records. They add context; none of them is a judgment."
        >
          <ul v-if="signalChips.length" class="flex flex-wrap gap-2">
            <li
              v-for="chip in signalChips"
              :key="chip"
              class="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700"
            >
              {{ chip }}
            </li>
          </ul>
          <p v-else class="text-sm text-slate-600">Nothing notable in the public records we track.</p>

          <div v-if="core.twin_n && core.twin_ratio" class="mt-4 border-t border-slate-100 pt-4">
            <h3 class="font-semibold text-slate-800">Identical homes on your block</h3>
            <p class="mt-1 text-sm text-slate-700">
              City records show <strong>{{ core.twin_n }}</strong> homes identical to this one in
              every recorded way. This home’s assessment is
              <strong>{{ pct(core.twin_ratio - 1, 1) }}</strong>
              {{ core.twin_ratio >= 1 ? 'above' : 'below' }} their middle value.
            </p>
            <InfoTip>
              Pennsylvania’s constitution requires uniform taxation: identical homes should get the
              same assessment. A big gap against identical neighbors is strong appeal evidence.
            </InfoTip>
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
          <table class="w-full text-left text-sm">
            <caption class="sr-only">Recorded facts about this home and their effect on value</caption>
            <thead>
              <tr class="border-b border-slate-200 text-slate-600">
                <th scope="col" class="py-2 pr-3 font-medium">Fact on file</th>
                <th scope="col" class="py-2 pr-3 font-medium">Recorded as</th>
                <th scope="col" class="py-2 font-medium">Effect on estimate</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="f in report.drivers.appeal_facts"
                :key="f.label"
                class="border-b border-slate-100"
              >
                <th scope="row" class="py-2 pr-3 font-normal">
                  {{ f.label }}
                  <span v-if="f.implausible" class="font-semibold text-over" role="img" aria-label="Looks unusual — double-check this one">
                    ⚠
                  </span>
                </th>
                <td class="py-2 pr-3">{{ f.recorded }}</td>
                <td class="py-2 tabular-nums">
                  {{ f.dollars >= 0 ? '+' : '−' }}{{ money(Math.abs(f.dollars)) }}
                </td>
              </tr>
            </tbody>
          </table>
          <p class="mt-2 text-xs text-slate-500">⚠ = this recorded value looks unusual for Philadelphia homes — double-check it.</p>
        </template>
        <p v-else class="text-sm text-slate-600">
          Compare the city’s recorded facts (size, condition, year built) with reality at
          <a :href="cityLink" rel="noopener" class="font-medium text-brand-600 underline"
            >property.phila.gov</a
          >.
        </p>

        <div class="mt-5 rounded-xl bg-brand-50 p-4 text-sm text-slate-800">
          <h3 class="font-bold text-brand-900">How to act on this (all free)</h3>
          <ol class="mt-2 list-decimal space-y-1.5 pl-5">
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
          <p class="mt-3">
            Details:
            <a
              href="https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/"
              rel="noopener"
              class="font-semibold text-brand-600 underline"
              >phila.gov: appeal a property assessment</a
            >
          </p>
        </div>
        <p class="mt-4 text-xs text-slate-500">
          This report is public information, not legal or appraisal advice. Estimates come from a
          statistical model and can be wrong for any single home — that’s why we show the range and
          the facts, not just a number.
          <span v-if="report?.screen_built">Data updated {{ report.screen_built }}.</span>
        </p>
      </SectionCard>
    </template>
  </div>
</template>
