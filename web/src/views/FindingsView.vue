<script setup lang="ts">
/** Findings — the story of what the model analysis actually found, in plain
 * language. Every figure is a measured result; provenance at the bottom.
 * Sources: docs/vertical-equity-report-card.md, docs/historical-redistribution.md,
 * docs/report-assessment-equity.md (repo). Deliberately NOT included here: any
 * per-race dollar claim — on the defensible (financed) sample that story
 * reverses, so it stays in the technical docs with its full caveats. */
import { SITE } from '@/config/site'
/** All figures come from web/src/data/siteStats.json — regenerate with
 * `philly export-web-stats` after every retrain (never hand-edit). */
import stats from '@/data/siteStats.json'

const t = stats.tiers_financed
const tiers = [
  { group: 'Cheapest fifth of homes', city: t.q1.opa_pct, ours: t.q1.model_pct },
  { group: 'Priciest fifth of homes', city: t.q5.opa_pct, ours: t.q5.model_pct },
]

const redis = stats.redistribution
/** Full years only for the chart (the partial current year would mislead). */
const shifted = redis.years.filter((y) => !y.partial).map((y) => ({ year: y.year, m: y.millions }))
const SHIFT_MAX = Math.max(...shifted.map((s) => Math.abs(s.m)), 1) * 1.1

const cash = stats.cash
const cashAllOf10 = Math.round(cash.share_all_pct / 10)
const cashQ1Of10 = Math.round(cash.share_q1_pct / 10)

function barW(pct: number): number {
  return (pct / 140) * 100
}
function colH(m: number): number {
  return (Math.abs(m) / SHIFT_MAX) * 100
}
</script>

<template>
  <div class="mx-auto max-w-2xl px-4 py-6 sm:py-8">
    <p class="text-caption font-bold uppercase tracking-[0.1em] text-brand-600">Findings</p>
    <h1 class="mt-2 font-display text-[28px] font-bold leading-tight text-ink sm:text-[34px]">
      What we found
    </h1>
    <p class="mt-2.5 text-base leading-relaxed text-body">
      We compared ten years of Philadelphia assessments with what homes actually sold for. Four
      findings matter most — including one in the city’s favor.
    </p>

    <!-- Finding 1: regressivity is real — and fixable -->
    <section class="mt-5 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 1</p>
      <h2 class="mt-1 text-title font-bold text-ink">
        Cheaper homes are over-assessed — and it doesn’t have to be that way.
      </h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        100% means the city’s value matches what homes really sell for. The cheapest fifth of
        Philadelphia homes is assessed at <strong>{{ t.q1.opa_pct }}%</strong> — owners pay tax on
        more value than their homes have. The priciest fifth sits at
        <strong>{{ t.q5.opa_pct }}%</strong>. Economists call this
        <em>regressivity</em>; in plain terms, it quietly shifts tax from expensive homes onto
        cheap ones.
      </p>

      <div
        class="mt-4"
        role="img"
        :aria-label="`Assessment level by home-value group. Cheapest fifth: city ${t.q1.opa_pct} percent, our model ${t.q1.model_pct} percent. Priciest fifth: city ${t.q5.opa_pct} percent, our model ${t.q5.model_pct} percent. 100 percent is fair.`"
      >
        <div v-for="tier in tiers" :key="tier.group" class="mb-3" aria-hidden="true">
          <p class="text-body-sm font-semibold text-ink">{{ tier.group }}</p>
          <div class="relative mt-1.5 space-y-1">
            <!-- fair line at 100% -->
            <div
              class="absolute -top-1 bottom-0 w-px border-l border-dashed border-[#8593a4]"
              :style="{ left: `${barW(100)}%` }"
            ></div>
            <div class="flex items-center gap-2">
              <div class="h-4 rounded-r-sm bg-[#9db1c7]" :style="{ width: `${barW(tier.city)}%` }"></div>
              <span class="money shrink-0 text-caption font-bold text-muted">City {{ tier.city }}%</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="h-4 rounded-r-sm bg-brand-600" :style="{ width: `${barW(tier.ours)}%` }"></div>
              <span class="money shrink-0 text-caption font-bold text-brand-600">Ours {{ tier.ours }}%</span>
            </div>
          </div>
        </div>
        <p class="text-caption text-faint" aria-hidden="true">dashed line = 100% (fair)</p>
      </div>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        The blue bars are the point: this pattern is not a foregone conclusion. Using only the
        city’s own open data, our model puts the same groups at
        <strong>{{ t.q1.model_pct }}%</strong> and <strong>{{ t.q5.model_pct }}%</strong> on the
        same sales — most of the gap is gone. Regressive assessments are a modeling problem, and
        modeling problems can be fixed.
        <RouterLink to="/trust" class="font-semibold text-brand-600 underline">See the proof</RouterLink>.
      </p>
      <p class="mt-2 text-caption text-muted">
        Measured on mortgage-financed sales the model never trained on.
      </p>
    </section>

    <!-- Finding 2: the dollars -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 2</p>
      <h2 class="mt-1 text-title font-bold text-ink">
        Over a decade, that shifted roughly a third of a billion dollars.
      </h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        Property tax is a fixed pie: every dollar the bottom over-pays, the top under-pays.
        Comparing each year’s roll to a fair one, lower-value homes over-paid about
        <strong>${{ redis.total_financed_musd }} million</strong> from
        {{ redis.year_span.replace('–', ' to ') }} (about ${{ redis.per_resident_usd }} per
        Philadelphian) — roughly <strong>$300–350 a year per lower-value home</strong> in the
        worst years. On a stricter all-sales benchmark the total is closer to
        <strong>${{ redis.total_raw_musd }} million</strong>.
      </p>

      <div class="mt-4" role="img" aria-label="Tax burden shifted from lower to higher value homes, by year, in millions: 55 in 2016, 59 in 2017, 57 in 2018, 30 in 2019, 15 in 2020, 1 in 2021, minus 2 in 2022, 38 in 2023, 38 in 2024, 64 in 2025.">
        <div class="flex h-28 gap-1" aria-hidden="true">
          <div v-for="s in shifted" :key="s.year" class="flex h-full flex-1 flex-col items-center justify-end">
            <span v-if="Math.abs(s.m) >= 30" class="money text-caption font-bold text-ink">{{ s.m }}</span>
            <div
              class="w-full rounded-t-sm"
              :class="s.m >= 0 ? 'bg-brand-600' : 'bg-[#9db1c7]'"
              :style="{ height: `${Math.max(2, colH(s.m))}%` }"
            ></div>
          </div>
        </div>
        <div class="mt-1 flex gap-1 border-t border-line pt-1" aria-hidden="true">
          <span v-for="s in shifted" :key="s.year" class="money flex-1 text-center text-caption text-faint">
            ’{{ String(s.year).slice(2) }}
          </span>
        </div>
        <p class="mt-1 text-caption text-faint" aria-hidden="true">$ millions shifted per year (financed benchmark)</p>
      </div>

      <div class="mt-3 rounded-md border border-gold-border bg-gold-soft p-3 text-body-sm leading-relaxed text-body">
        <strong class="text-gold-700">The 2020–22 dip does not mean the problem was fixed.</strong> The city froze
        assessments while prices boomed, so rising prices temporarily hid the pattern. It snapped
        right back with the 2023 reassessment.
      </div>
    </section>

    <!-- Finding 3: two markets -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 3</p>
      <h2 class="mt-1 text-title font-bold text-ink">Philadelphia has two housing markets.</h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        About <strong>{{ cashAllOf10 }} in 10</strong> Philadelphia home sales are all-cash —
        investors and wholesalers, concentrated in disinvested neighborhoods — and those homes
        sell for roughly <strong>{{ Math.abs(cash.discount_pct ?? 0) }}% less</strong> than
        financed homes in the same district. In the cheapest fifth of recent sales,
        <strong>{{ cashQ1Of10 }} in 10</strong> are cash.
      </p>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        This complicates the story honestly: measured against regular mortgage-financed sales, the
        city’s fairness problem shrinks a lot. Much of the unfairness lives in the
        <em>cash market</em> — homes taxed on values they cannot actually fetch. Any serious fix
        has to decide which market an assessment should reflect. We publish both views.
      </p>
    </section>

    <!-- Finding 4: in the city's favor -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 4 — IN THE CITY’S FAVOR</p>
      <h2 class="mt-1 text-title font-bold text-ink">The same pattern shows up across the country.</h2>
      <ul class="mt-1.5 list-disc space-y-1.5 pl-5 text-body-sm leading-relaxed text-body">
        <li>
          <strong>No number-gaming.</strong> We tested for “sales chasing” — quietly matching
          assessments to recent sales so official studies look good. Philadelphia comes back clean.
        </li>
        <li>
          <strong>Almost every city has this pattern.</strong> Research covering ~26 million U.S.
          sales finds the cheapest homes assessed at roughly twice the rate of the most expensive,
          nearly everywhere. Philadelphia isn’t uniquely bad — it sits inside a structural,
          nationwide failure. (Which is also why Finding 1 matters: the fix is a method, not a
          miracle.)
        </li>
      </ul>
    </section>

    <!-- what we do about it -->
    <section class="mt-4 rounded-xl border border-line-soft bg-brand-50 p-4 sm:p-5">
      <h2 class="text-title font-bold text-brand-900">What this site does about it</h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        A fairer model, free for anyone to check their own home — plus the evidence to fix wrong
        records or appeal.
        <RouterLink to="/" class="font-semibold text-brand-600 underline">Check your home</RouterLink>,
        <RouterLink to="/map" class="font-semibold text-brand-600 underline">explore the map</RouterLink>,
        or read
        <RouterLink to="/trust" class="font-semibold text-brand-600 underline">why you can trust these numbers</RouterLink>.
      </p>
    </section>

    <p class="mt-4 text-caption leading-normal text-faint">
      Measured on Philadelphia deed records {{ redis.year_span }}; model run
      {{ stats.meta.model_run_id }}, regenerated {{ stats.meta.generated_at }} via
      <code>philly export-web-stats</code>. Full methods,
      caveats, and the analyses we deliberately do not headline (including why per-group dollar
      claims need care) are in the
      <a :href="SITE.modelDocsUrl" rel="noopener" class="font-semibold text-brand-600 underline"
        >technical documentation</a
      >
      and
      <a :href="SITE.githubUrl" rel="noopener" class="font-semibold text-brand-600 underline"
        >the open repository</a
      >.
    </p>
  </div>
</template>
