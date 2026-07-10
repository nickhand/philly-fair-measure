<script setup lang="ts">
/** Findings — the story of what the model analysis actually found, in plain
 * language. Every figure is a measured result; provenance at the bottom.
 * Sources: docs/vertical-equity-report-card.md, docs/historical-redistribution.md,
 * docs/report-assessment-equity.md (repo). Deliberately NOT included here: any
 * per-race dollar claim — on the defensible (financed) sample that story
 * reverses, so it stays in the technical docs with its full caveats. */
import { SITE } from '@/config/site'
/** All figures come from web/src/data/siteStats.json — regenerate with
 * `fair-measure export-web-stats` after every retrain (never hand-edit). */
import stats from '@/data/siteStats.json'

const t = stats.tiers_financed
const tiers = [
  { group: 'Cheapest fifth of homes', city: t.q1.opa_pct, ours: t.q1.model_pct },
  { group: 'Priciest fifth of homes', city: t.q5.opa_pct, ours: t.q5.model_pct },
]

/** The artifact-robust check: the same test re-binned by NEIGHBORHOOD price
 * level (all sales), so one bad low sale can't fake the pattern. */
const rbNbhd = stats.equity_robustness.all_sales.neighborhood
const rbPct = (r: number) => Math.round(r * 100)

const redis = stats.redistribution
/** Full years only for the chart (the partial current year would mislead). */
const shifted = redis.years.filter((y) => !y.partial).map((y) => ({ year: y.year, m: y.millions }))
const SHIFT_MAX = Math.max(...shifted.map((s) => Math.abs(s.m)), 1) * 1.1
/** Worst full year, for the copy — derived, never hand-entered. */
const worstYearM = Math.max(...shifted.map((s) => s.m), 0)
/** Screen-reader description of the bar chart, built from the same data. */
const shiftAria =
  'Tax burden shifted from lower to higher value homes, by year, in millions: ' +
  shifted.map((s) => `${s.m < 0 ? 'minus ' : ''}${Math.abs(s.m)} in ${s.year}`).join(', ') +
  '.'

const cash = stats.cash
const cashAllOf10 = Math.round(cash.share_all_pct / 10)
const cashQ1Of10 = Math.round(cash.share_q1_pct / 10)

function barW(pct: number): number {
  return (pct / 140) * 100
}
function colH(m: number): number {
  return (Math.abs(m) / SHIFT_MAX) * 100
}

const shift = stats.tax_shift
/** Per-home yearly tax change by value quintile, for the diverging bars. */
const shiftTiers = shift.tiers
const SHIFT_HOME_MAX = Math.max(...shiftTiers.map((s) => Math.abs(s.home_usd)), 1)
/** Bar half-width from the zero centerline, as a % of the track. */
function shiftW(usd: number): number {
  return (Math.abs(usd) / SHIFT_HOME_MAX) * 46
}
const taxShiftAria =
  'Change in a typical home’s yearly tax bill by value group if the city adopted our ' +
  'assessments at today’s rate: ' +
  shiftTiers
    .map((s) =>
      s.home_usd < 0
        ? `${s.name} pays ${Math.abs(s.home_usd)} dollars less`
        : `${s.name} pays ${s.home_usd} dollars more`,
    )
    .join('; ') +
  '.'
</script>

<template>
  <div class="mx-auto max-w-2xl px-4 py-6 sm:py-8">
    <p class="text-caption font-bold uppercase tracking-[0.1em] text-brand-600">Findings</p>
    <h1 class="mt-2 font-display text-[28px] font-bold leading-tight text-ink sm:text-[34px]">
      What we found
    </h1>
    <p class="mt-2.5 text-base leading-relaxed text-body">
      We compared ten years of Philadelphia assessments with what homes actually sold for. Five
      findings matter most, including one in the city’s favor.
    </p>

    <!-- Finding 1: regressivity is real — and fixable -->
    <section class="mt-5 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 1</p>
      <h2 class="mt-1 text-title font-bold text-ink">
        Cheaper homes are over-assessed, and it doesn’t have to be this way.
      </h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        100% means the city’s value matches what homes really sell for. The cheapest fifth of
        Philadelphia homes is assessed at <strong>{{ t.q1.opa_pct }}%</strong>. Those owners pay tax
        on more value than their homes have. The priciest fifth sits at
        <strong>{{ t.q5.opa_pct }}%</strong>. Economists call this <em>regressivity</em>. In plain
        words, it quietly shifts tax off expensive homes and onto cheap ones.
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
        The blue bars show the point: this pattern does not have to happen. Using only the
        city’s own open data, our model puts the same groups at
        <strong>{{ t.q1.model_pct }}%</strong> and <strong>{{ t.q5.model_pct }}%</strong> on the
        same sales. Most of the gap is gone. Regressive assessments are a modeling problem, and
        modeling problems can be fixed.
        <RouterLink to="/trust" class="font-semibold text-brand-600 underline">See the proof</RouterLink>.
      </p>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        A fair question: could bad data fake this picture? A foreclosure or a family deal can make
        one home look cheap when its neighborhood is not. So we reran the test the skeptic’s way,
        grouping homes by their <em>neighborhood’s</em> price level instead of their own, counting
        every sale. The pattern holds. The city still values the cheapest fifth of neighborhoods at
        <strong>{{ rbPct(rbNbhd.opa.q1) }}%</strong> of what homes there sell for, and the priciest
        fifth at <strong>{{ rbPct(rbNbhd.opa.q5) }}%</strong>. Our model reads
        {{ rbPct(rbNbhd.model.q1) }}% and {{ rbPct(rbNbhd.model.q5) }}%, close to flat.
      </p>
      <p class="mt-2 text-caption text-muted">
        Bars measured on mortgage-financed sales the model never trained on; the neighborhood check
        counts every arms-length sale.
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
        Philadelphian). <strong>${{ worstYearM }} million of that came in the worst single
        year.</strong> On a stricter all-sales benchmark the total is closer to
        <strong>${{ redis.total_raw_musd }} million</strong>.
      </p>

      <div class="mt-4" role="img" :aria-label="shiftAria">
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
        <strong class="text-gold-700">The 2020 to 2022 dip does not mean the problem was fixed.</strong> The city
        froze assessments while prices boomed, so rising prices hid the pattern for a while. It
        snapped right back with the 2023 reassessment.
      </div>
    </section>

    <!-- Finding 3: two markets -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 3</p>
      <h2 class="mt-1 text-title font-bold text-ink">Philadelphia has two housing markets.</h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        About <strong>{{ cashAllOf10 }} in 10</strong> Philadelphia home sales are all-cash. These
        are mostly investors and wholesalers, and they cluster in disinvested neighborhoods. Those
        homes sell for roughly <strong>{{ Math.abs(cash.discount_pct ?? 0) }}% less</strong> than
        financed homes in the same district. In the cheapest fifth of recent sales,
        <strong>{{ cashQ1Of10 }} in 10</strong> are cash.
      </p>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        This part makes the story more complicated. Measured against regular mortgage-financed
        sales, the city’s fairness problem shrinks a lot. Much of the unfairness lives in the
        <em>cash market</em>, where homes are taxed on values they cannot actually fetch. Any real
        fix has to decide which market an assessment should reflect. We show both views.
      </p>
    </section>

    <!-- Finding 4: in the city's favor -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 4 · IN THE CITY’S FAVOR</p>
      <h2 class="mt-1 text-title font-bold text-ink">The same pattern shows up across the country.</h2>
      <ul class="mt-1.5 list-disc space-y-1.5 pl-5 text-body-sm leading-relaxed text-body">
        <li>
          <strong>No number-gaming.</strong> We tested for “sales chasing,” which means quietly
          matching assessments to recent sales so official studies look good. Philadelphia comes
          back clean.
        </li>
        <li>
          <strong>Almost every city has this pattern.</strong> Research covering about 26 million
          U.S. sales finds the cheapest homes assessed at roughly twice the rate of the most
          expensive, nearly everywhere. Philadelphia isn’t uniquely bad. It sits inside a
          structural, nationwide failure. That is also why Finding 1 matters: the fix is a method
          other cities could use too.
        </li>
      </ul>
    </section>

    <!-- Finding 5: accurate assessments = found revenue + a fair-share correction -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-caption font-bold text-brand-600">FINDING 5 · THE FIX</p>
      <h2 class="mt-1 text-title font-bold text-ink">
        Make the wealthy pay their fair share.
      </h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        Cities everywhere are scrambling for revenue, and passing a new tax is a long, hard fight.
        Philadelphia has an easier option that needs no new law and no rate hike: fix the assessments
        it already has. Today the priciest homes are under-assessed, so their owners are billed on
        less than their homes are worth.
      </p>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        Correcting that makes the wealthiest homeowners pay their fair share, and it gives the
        over-assessed cheapest homes a break. The typical priciest-fifth home would pay about
        <strong>${{ shift.priciest_home_usd }} more</strong> a year; the typical cheapest-fifth home
        pays about <strong>${{ Math.abs(shift.cheapest_home_usd) }} less</strong>.
      </p>
      <p class="mt-2 text-body-sm leading-relaxed text-body">
        Because the increase at the top outweighs the relief at the bottom, the city comes out ahead:
        an estimated <strong>${{ shift.new_revenue_musd }} million a year</strong> it is not
        collecting today, at the same rate, with no new tax. Struggling for revenue and struggling
        for fairness turn out to be the same problem, with the same fix.
      </p>

      <div class="mt-4" role="img" :aria-label="taxShiftAria">
        <p class="mb-2 text-caption text-faint" aria-hidden="true">
          Change in a typical home’s yearly tax bill, by value group
        </p>
        <div class="space-y-2" aria-hidden="true">
          <div v-for="s in shiftTiers" :key="s.name">
            <div class="flex items-baseline justify-between">
              <span class="text-caption font-semibold capitalize text-ink">{{ s.name }}</span>
              <span
                class="money text-caption font-bold"
                :class="s.home_usd < 0 ? 'text-muted' : 'text-brand-600'"
                >{{ s.home_usd < 0 ? `−$${Math.abs(s.home_usd)}` : `+$${s.home_usd}` }}</span
              >
            </div>
            <div class="relative mt-1 h-3.5">
              <div class="absolute inset-y-0 left-1/2 w-px bg-[#8593a4]"></div>
              <div
                class="absolute top-0 h-3.5"
                :class="s.home_usd < 0 ? 'rounded-l-sm bg-[#9db1c7]' : 'rounded-r-sm bg-brand-600'"
                :style="
                  s.home_usd < 0
                    ? { right: '50%', width: `${shiftW(s.home_usd)}%` }
                    : { left: '50%', width: `${shiftW(s.home_usd)}%` }
                "
              ></div>
            </div>
          </div>
        </div>
        <p class="mt-1.5 text-center text-caption text-faint" aria-hidden="true">
          ← pays less · pays more →
        </p>
      </div>

      <div class="mt-3 rounded-md bg-brand-50 p-3 text-body-sm leading-relaxed text-body">
        <strong class="text-brand-900">No new tax. No new law. No rate hike.</strong> Just an
        accurate roll. The wealthiest homeowners are under-assessed right now, so making them pay
        their fair share is the simplest tax reform on the table, and it pays for itself.
      </div>
      <p class="mt-2 text-caption text-muted">
        An estimate across every home the model scores; the corrected values run about
        {{ shift.base_change_pct }}% higher citywide, concentrated in the most expensive homes.
        Residential and condo property only. The city could instead keep total collections flat and
        cut the rate for everyone; either way the regressive tilt is gone.
      </p>
    </section>

    <!-- what we do about it -->
    <section class="mt-4 rounded-xl border border-line-soft bg-brand-50 p-4 sm:p-5">
      <h2 class="text-title font-bold text-brand-900">What this site does about it</h2>
      <p class="mt-1.5 text-body-sm leading-relaxed text-body">
        A fairer model, free for anyone to check their own home, plus the evidence to fix wrong
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
      <code>fair-measure export-web-stats</code>. Full methods,
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
