<script setup lang="ts">
/** Public annual assessment report. All measured claims come from generated site stats. */
import { useRouter } from 'vue-router'
import AddressSearch from '@/components/search/AddressSearch.vue'
import { SITE } from '@/config/site'
import stats from '@/data/siteStats.json'
import { annualReportNarrative } from '@/utils/annualReportNarrative'
import { num } from '@/utils/format'
import type { SearchHit } from '@/api/types'

const router = useRouter()
const report = stats.annual_report
const equity = report.vertical_equity
const uniformity = report.uniformity
const saleTest = stats.iaao_card
const narrative = annualReportNarrative(report)

const generatedDate = formatDate(stats.meta.generated_at)
const effectiveDate = formatDate(report.effective_date)
const benchmarkDate = formatDate(report.benchmark_date)

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

/** One shared scale, padded to the exported tier values and anchored at 100%. */
const ratioValues = report.tiers.flatMap((tier) => [tier.old_ratio_pct, tier.new_ratio_pct])
const ratioMin = Math.floor((Math.min(100, ...ratioValues) - 5) / 5) * 5
const ratioMax = Math.ceil((Math.max(100, ...ratioValues) + 5) / 5) * 5

function ratioPosition(value: number): string {
  return `${Math.max(0, Math.min(100, ((value - ratioMin) / (ratioMax - ratioMin)) * 100))}%`
}

function ratioLine(tier: (typeof report.tiers)[number]): { left: string; width: string } {
  const oldPos = Number.parseFloat(ratioPosition(tier.old_ratio_pct))
  const newPos = Number.parseFloat(ratioPosition(tier.new_ratio_pct))
  return { left: `${Math.min(oldPos, newPos)}%`, width: `${Math.abs(newPos - oldPos)}%` }
}

function assessmentPosition(value: number): string {
  const difference = value - 100
  if (Math.abs(difference) < 0.5) return 'matches our estimate'
  return `${Math.abs(difference).toFixed(0)}% ${difference > 0 ? 'above' : 'below'} our estimate`
}

function goToProperty(hit: SearchHit) {
  router.push({ name: 'property', params: { parcelId: hit.parcel_id } })
}
</script>

<template>
  <article class="bg-paper pb-10">
    <header class="border-b border-line bg-white">
      <div class="mx-auto max-w-4xl px-4 py-8 sm:py-11">
        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded-full bg-brand-50 px-2.5 py-1 text-caption font-bold uppercase tracking-[0.08em] text-brand-700">
            Tax Year {{ report.tax_year }}
          </span>
          <span class="rounded-full border border-gold-border bg-gold-soft px-2.5 py-1 text-caption font-bold uppercase tracking-[0.08em] text-gold-700">
            {{ narrative.statusLabel }}
          </span>
          <span class="text-caption text-muted">Updated {{ generatedDate }}</span>
        </div>

        <h1 class="mt-4 max-w-3xl font-display text-[31px] font-bold leading-[1.08] tracking-tight text-ink sm:text-[46px]">
          {{ narrative.headline }}
        </h1>
        <p class="mt-3 max-w-3xl text-base leading-relaxed text-body sm:text-lg">
          {{ narrative.lead }}
        </p>

        <nav aria-label="Report sections" class="mt-6 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-4 text-body-sm font-semibold">
          <a href="#finding" class="text-brand-600 underline underline-offset-2">What happened</a>
          <a href="#next" class="text-brand-600 underline underline-offset-2">Check your home</a>
          <a href="#methods" class="text-brand-600 underline underline-offset-2">How we checked</a>
        </nav>
      </div>
    </header>

    <div class="mx-auto max-w-4xl px-4">
      <section id="finding" class="scroll-mt-5 pt-8 sm:pt-11">
        <p class="text-caption font-bold uppercase tracking-[0.08em] text-brand-600">What happened</p>
        <h2 class="mt-1 max-w-3xl font-display text-2xl font-bold text-ink sm:text-3xl">
          {{ narrative.findingHeadline }}
        </h2>
        <p class="mt-2 max-w-3xl text-body-sm leading-relaxed text-body">
          We ranked homes by our estimate and split them into five equal groups. A ratio above
          100% means OPA assessed the group above our estimate. Below 100% means OPA assessed it below.
        </p>

        <div class="mt-5 border-y border-line">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line-faint py-3 text-caption text-muted">
            <p><strong class="text-ink">OPA assessment as a share of our estimate</strong></p>
            <p class="flex flex-wrap items-center gap-x-3 gap-y-1" aria-hidden="true">
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full border-2 border-brand-600 bg-white"></span>Old assessment ({{ report.comparison_year }})</span>
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-brand-600"></span>New assessment ({{ report.tax_year }})</span>
            </p>
          </div>

          <div class="grid gap-2 border-b border-line-faint py-2 sm:grid-cols-[145px_1fr_145px]">
            <span class="hidden sm:block" aria-hidden="true"></span>
            <div class="flex items-center justify-between text-caption font-bold text-body">
              <span>← Below our estimate</span>
              <span>Above our estimate →</span>
            </div>
          </div>

          <div class="divide-y divide-line-faint">
            <div v-for="tier in report.tiers" :key="tier.tier" class="grid gap-2 py-3 sm:grid-cols-[145px_1fr_145px] sm:items-center">
              <p class="text-body-sm font-bold text-ink">{{ tier.label }}</p>
              <div
                class="relative h-7"
                role="img"
                :aria-label="`${tier.label}: ${tier.old_ratio_pct}% in TY${report.comparison_year}, ${tier.new_ratio_pct}% in TY${report.tax_year}. ${assessmentPosition(tier.new_ratio_pct)}.`"
              >
                <div class="absolute inset-x-0 top-3 h-px bg-line"></div>
                <div class="absolute top-1 h-5 w-px bg-[#7b8797]" :style="{ left: ratioPosition(100) }"></div>
                <div class="absolute top-[11px] h-1 bg-brand-300" :style="ratioLine(tier)"></div>
                <span class="absolute top-[7px] h-3 w-3 -translate-x-1/2 rounded-full border-2 border-brand-600 bg-white" :style="{ left: ratioPosition(tier.old_ratio_pct) }"></span>
                <span class="absolute top-[7px] h-3 w-3 -translate-x-1/2 rounded-full bg-brand-600 ring-2 ring-white" :style="{ left: ratioPosition(tier.new_ratio_pct) }"></span>
              </div>
              <div class="sm:text-right">
                <p class="money text-body-sm font-bold text-ink">{{ tier.old_ratio_pct.toFixed(0) }}% → {{ tier.new_ratio_pct.toFixed(0) }}%</p>
                <p class="text-caption text-muted">{{ assessmentPosition(tier.new_ratio_pct) }}</p>
              </div>
            </div>
          </div>
        </div>

        <p class="mt-3 max-w-3xl text-caption leading-relaxed text-muted">
          “Cheapest” means the 20% with the lowest model estimates—not the cheapest recent sales.
          The chart includes {{ num(report.correction.n_reliable) }} homes without a known data
          warning. We left the other {{ report.correction.data_warning_pct.toFixed(0) }}% out of
          this fairness comparison.
        </p>
        <p class="mt-4 max-w-3xl border-l-2 border-brand-300 pl-3 text-body-sm leading-relaxed text-body">
          <strong class="text-ink">{{ narrative.calloutLead }}</strong>
          {{ narrative.callout }}
        </p>
      </section>

      <section id="next" class="scroll-mt-5 pt-9 sm:pt-12">
        <p class="text-caption font-bold uppercase tracking-[0.08em] text-brand-600">Your home</p>
        <h2 class="mt-1 max-w-3xl font-display text-2xl font-bold text-ink sm:text-3xl">
          Check your address before drawing a conclusion.
        </h2>
        <p class="mt-2 max-w-3xl text-body-sm leading-relaxed text-body">
          The citywide pattern does not decide whether one home is assessed correctly.
        </p>
        <div class="mt-4 max-w-xl">
          <AddressSearch @select="goToProperty" />
        </div>

        <div class="mt-6 grid border-y border-line sm:grid-cols-2">
          <div class="py-4 sm:pr-6">
            <h3 class="text-title font-bold text-ink">Think OPA’s value is wrong?</h3>
            <RouterLink to="/appeal" class="mt-2 inline-block text-body-sm font-bold text-brand-600 underline">See the appeal steps →</RouterLink>
          </div>
          <div class="border-t border-line py-4 sm:border-l sm:border-t-0 sm:pl-6">
            <h3 class="text-title font-bold text-ink">Need help paying the bill?</h3>
            <a :href="SITE.propertyTaxReliefUrl" rel="noopener" class="mt-2 inline-block text-body-sm font-bold text-brand-600 underline">See City tax-relief programs →</a>
          </div>
        </div>
      </section>

      <section id="methods" class="scroll-mt-5 pt-9 sm:pt-12">
        <details class="border-y border-line py-3">
          <summary class="cursor-pointer text-body-sm font-bold text-brand-600 underline underline-offset-2">
            Methods, technical measures, and limits
          </summary>
          <div class="mt-4 max-w-3xl space-y-4 text-body-sm leading-relaxed text-body">
            <p>
              We compared {{ num(report.n_properties) }} single-family homes with values in both
              TY{{ report.comparison_year }} and TY{{ report.tax_year }}. We left known data-warning
              records out of the fairness totals.
            </p>
            <p>
              Why use our estimate as the benchmark? {{ narrative.benchmarkMethodsIntro }}: PRD
              {{ saleTest.model.prd.toFixed(3) }} versus {{ saleTest.opa.prd.toFixed(3) }}, PRB
              {{ saleTest.model.prb.toFixed(3) }} versus {{ saleTest.opa.prb.toFixed(3) }}, and VEI
              {{ saleTest.model.vei.toFixed(1) }}% versus {{ saleTest.opa.vei.toFixed(1) }}%.
              Values closer to 1.000 for PRD and zero for PRB and VEI are fairer by home value.
              The model is still a check, not ground truth.
            </p>
            <p>
              <template v-if="report.status === 'provisional'">
                The new assessments take effect {{ effectiveDate }}.
                There are no sales from that tax year yet, so we compared both years with the same
                model estimate, dated {{ benchmarkDate }}.
              </template>
              <template v-else>
                The assessments took effect {{ effectiveDate }}.
                We compared both years with the same model estimate, dated {{ benchmarkDate }}.
              </template>
            </p>
            <p>
              {{ narrative.opaStudyIntro }} Our check asks a different question: using one independent
              estimate for both years, did the result become more or less fair by home value? The two
              studies use different benchmarks and can reach different conclusions.
            </p>
            <p>
              Against that benchmark, {{ narrative.standardMetricsIntro.toLowerCase() }}: PRD
              {{ equity.prd.old.toFixed(3) }} → {{ equity.prd.new.toFixed(3) }}, PRB
              {{ equity.prb.old.toFixed(3) }} → {{ equity.prb.new.toFixed(3) }}, and VEI
              {{ equity.vei.old.toFixed(1) }}% → {{ equity.vei.new.toFixed(1) }}%. COD, which measures
              consistency rather than fairness by value, changed from {{ uniformity.old_cod.toFixed(1) }}
              to {{ uniformity.new_cod.toFixed(1) }}.
            </p>
            <div class="flex flex-wrap gap-x-5 gap-y-2 font-semibold">
              <a :href="report.sources.opa_methodology_url" rel="noopener" class="text-brand-600 underline">OPA’s TY{{ report.tax_year }} methods</a>
              <a :href="report.sources.opa_ratio_studies_url" rel="noopener" class="text-brand-600 underline">OPA’s ratio studies</a>
              <a :href="report.sources.iaao_ratio_study_url" rel="noopener" class="text-brand-600 underline">IAAO ratio-study guide</a>
              <a :href="SITE.modelDocsUrl" rel="noopener" class="text-brand-600 underline">Our model</a>
              <a :href="report.sources.notebook_url" rel="noopener" class="text-brand-600 underline">Reproduce this report</a>
            </div>
            <p class="text-caption text-faint">
              Model run {{ stats.meta.model_run_id }} · report generated {{ stats.meta.generated_at }} · Philadelphia OPA open data.
            </p>
          </div>
        </details>
      </section>
    </div>
  </article>
</template>
