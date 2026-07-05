<script setup lang="ts">
/** The proof page: why the numbers on this site can be trusted.
 *
 * Structure resolves the plain-language/technical tension by layering:
 * plain claims → the official test as a scored card → how we tested →
 * what we say in the city's favor → what we can NOT claim → full technical
 * tables behind <details> for the reader who wants them.
 *
 * Numbers: out-of-time test of baseline run 20260705T015912Z (n ≈ 19.5k
 * arms-length sales) — docs/vertical-equity-report-card.md in the repo.
 * Regenerate when the model retrains. */
import { Check, Scale, X } from 'lucide-vue-next'
import SectionCard from '@/components/ui/SectionCard.vue'
import { SITE } from '@/config/site'
import InfoTip from '@/components/ui/InfoTip.vue'

/** IAAO-standard basis (time-adjusted, 3×IQR-trimmed) — the official convention. */
const officialCard = [
  {
    q: 'Is the overall level right?',
    stat: 'Median ratio',
    target: '0.90 – 1.10',
    city: '0.94',
    cityPass: true,
    ours: '0.97',
    oursPass: true,
  },
  {
    q: 'Do similar homes get similar values?',
    stat: 'COD (uniformity)',
    target: '≤ 15',
    city: '25.4',
    cityPass: false,
    ours: '17.0',
    oursPass: false,
    oursNote: 'just above — within IAAO tolerance for old rowhome stock',
  },
  {
    q: 'Are cheap homes over-valued vs expensive ones?',
    stat: 'PRD (vertical equity)',
    target: '0.98 – 1.03',
    city: '1.115',
    cityPass: false,
    ours: '1.029',
    oursPass: true,
  },
  {
    q: 'Same question, the preferred test',
    stat: 'PRB (vertical equity)',
    target: 'within ±0.05',
    city: '−0.148',
    cityPass: false,
    ours: '−0.022',
    oursPass: true,
  },
]

/** Full-sample basis (no trim) — what every homeowner actually experiences. */
const fullCard = [
  { stat: 'Median ratio', target: '0.90 – 1.10', city: '0.983', ours: '0.975' },
  { stat: 'COD', target: '≤ 15', city: '34.5', ours: '25.9' },
  { stat: 'PRD', target: '0.98 – 1.03', city: '1.190', ours: '1.071' },
  { stat: 'PRB', target: '±0.05', city: '−0.234', ours: '−0.060' },
  { stat: 'Typical error (MAPE)', target: '—', city: '34.0%', ours: '25.4%' },
]
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6 px-4 py-8">
    <div>
      <p class="text-caption font-bold uppercase tracking-[0.1em] text-brand-600">The proof</p>
      <h1 class="mt-2 font-display text-[28px] font-bold leading-tight text-ink sm:text-[34px]">Why trust these numbers?</h1>
      <p class="mt-2.5 text-base leading-relaxed text-body">
        You don’t have to take our word for it. This page shows the test we’re graded on, how we
        made sure the test was fair, and where our model still falls short.
      </p>
    </div>

    <!-- the three plain claims -->
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="rounded-lg border border-line-soft bg-white p-4">
        <span
          class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50"
          aria-hidden="true"
        >
          <Scale :size="20" class="text-brand-600" />
        </span>
        <p class="mt-2 text-body-sm text-body">
          <strong class="text-ink">We use the official test.</strong> Assessors nationwide are
          graded with the same ratio-study standards we apply here — not a test we invented.
        </p>
      </div>
      <div class="rounded-lg border border-line-soft bg-white p-4">
        <span
          class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50"
          aria-hidden="true"
        >
          <Check :size="20" class="text-brand-600" />
        </span>
        <p class="mt-2 text-body-sm text-body">
          <strong class="text-ink">We test the hard way.</strong> Our model is graded only on sales
          it never saw — like grading a student on questions they never studied.
        </p>
      </div>
      <div class="rounded-lg border border-line-soft bg-white p-4">
        <span
          class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50"
          aria-hidden="true"
        >
          <X :size="20" class="text-brand-600" />
        </span>
        <p class="mt-2 text-body-sm text-body">
          <strong class="text-ink">We publish our misses.</strong> Where the model falls short, this
          page says so.
        </p>
      </div>
    </div>

    <!-- the head-to-head -->
    <SectionCard
      title="The official test, head to head"
      subtitle="The IAAO ratio study compares values to what homes actually sold for. Here is the city's roll and our model on the exact same sales, scored the official way."
    >
      <div class="space-y-3">
        <div
          v-for="row in officialCard"
          :key="row.stat"
          class="rounded-md border border-line-faint p-3"
        >
          <p class="font-bold text-ink">{{ row.q }}</p>
          <p class="text-caption text-faint">{{ row.stat }} · acceptable: {{ row.target }}</p>
          <div class="mt-2 grid grid-cols-2 gap-3 text-body-sm">
            <div class="flex items-center gap-2">
              <span
                class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                :class="row.cityPass ? 'bg-fair-soft text-fair' : 'bg-over-soft text-over'"
              >
                <Check v-if="row.cityPass" :size="14" aria-hidden="true" />
                <X v-else :size="14" aria-hidden="true" />
              </span>
              <span>
                City’s roll: <strong class="money">{{ row.city }}</strong>
                <span class="sr-only">{{ row.cityPass ? '— passes' : '— fails' }}</span>
              </span>
            </div>
            <div class="flex items-center gap-2">
              <span
                class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                :class="row.oursPass ? 'bg-fair-soft text-fair' : 'bg-over-soft text-over'"
              >
                <Check v-if="row.oursPass" :size="14" aria-hidden="true" />
                <X v-else :size="14" aria-hidden="true" />
              </span>
              <span>
                Our model: <strong class="money">{{ row.ours }}</strong>
                <span class="sr-only">{{ row.oursPass ? '— passes' : '— fails' }}</span>
                <span v-if="row.oursNote" class="text-muted"> ({{ row.oursNote }})</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <p class="mt-3 text-body-sm text-body">
        <strong>The bottom line:</strong> our model passes both fairness-across-price tests; the
        city’s roll fails all three of the strict tests. Both were scored on the same homes and
        the same sales.
      </p>
      <InfoTip label="What these tests mean, in plain words">
        “Median ratio” asks whether values are centered on real prices. “COD” asks whether similar
        homes get similar treatment. “PRD” and “PRB” ask the fairness question that matters most:
        are cheaper homes valued too high relative to expensive ones? That pattern — cheap homes
        over-assessed — means lower-income owners quietly pay more than their share of tax.
      </InfoTip>
    </SectionCard>

    <!-- how we kept the test fair -->
    <SectionCard title="How we made sure the test was fair">
      <ul class="list-disc space-y-2 pl-5 text-body">
        <li>
          <strong>The model never sees the answer key.</strong> We grade it only on sales that
          happened <em>after</em> everything it learned from — the hardest version of the test, and
          the one that matches how assessments really work.
        </li>
        <li>
          <strong>The city’s number is never an input.</strong> Our model can’t copy OPA’s value —
          it never sees it. Otherwise the comparison would be circular.
        </li>
        <li>
          <strong>Two methods must agree before we flag your home.</strong> A property is only
          marked “may be too high” when two independent statistical methods both put the city’s
          value outside the likely range.
        </li>
        <li>
          <strong>No people-data, ever.</strong> Race, income, and anything about who lives in a
          home are never inputs. We use them only afterward, to check the model for neighborhood
          bias.
        </li>
      </ul>
    </SectionCard>

    <!-- what we say in the city's favor -->
    <SectionCard
      title="What we found in the city’s favor"
      subtitle="Two findings came out on the city’s side."
    >
      <ul class="list-disc space-y-2 pl-5 text-body">
        <li>
          <strong>OPA is not gaming its numbers.</strong> A known trick called “sales chasing” —
          quietly matching assessments to recent sales so the official study looks good — shows
          <em>no evidence</em> in Philadelphia. We ran the standard detection test across two tax
          years; it came back clean each time.
        </li>
        <li>
          <strong>This is a national problem, not a Philadelphia scandal.</strong> Research covering
          roughly 26 million U.S. sales finds the same pattern almost everywhere: the cheapest homes
          are assessed at roughly twice the rate of the most expensive, relative to what they sell
          for. Philadelphia sits inside a structural, nationwide failure — a better model moves it;
          nothing fully fixes it yet.
        </li>
      </ul>
    </SectionCard>

    <!-- what we cannot claim -->
    <SectionCard title="What we can NOT claim">
      <div class="rounded-md border border-gold-border bg-gold-soft p-4">
        <ul class="list-disc space-y-2 pl-5 text-body">
          <li>
            <strong>Nobody passes the unfiltered test — including us.</strong> The official standard
            excludes foreclosures, cash-market distress sales, and extreme cases. Scored on
            <em>every</em> sale with no exclusions, the city’s roll fails badly and our model fails
            too — by a much smaller margin (see the full table below). “Passes the official test”
            and “fair to every neighborhood” are different claims.
          </li>
          <li>
            <strong>Our model is still imperfect on cheap homes.</strong> Homes that sell for cash
            in disinvested neighborhoods are the hardest to value — for the city and for us. Our
            estimates there carry wider ranges, and we show those ranges instead of hiding them.
          </li>
          <li>
            <strong>One home can still be wrong.</strong> These are statistics. That’s why your
            report shows the facts to check, not just a verdict.
          </li>
        </ul>
      </div>
    </SectionCard>

    <!-- technical reader -->
    <SectionCard
      title="For the technical reader"
      subtitle="The full numbers, definitions, and how to reproduce every figure on this page."
    >
      <details class="rounded-md border border-line-faint p-3">
        <summary class="cursor-pointer font-semibold text-brand-600">
          Full table — official IAAO basis (time-adjusted, 3×IQR-trimmed)
        </summary>
        <table class="mt-3 w-full text-left text-body-sm">
          <caption class="sr-only">IAAO-standard ratio statistics, city versus our model</caption>
          <thead>
            <tr class="border-b border-line text-muted">
              <th scope="col" class="py-2 pr-3 font-medium">Statistic</th>
              <th scope="col" class="py-2 pr-3 font-medium">Acceptable</th>
              <th scope="col" class="py-2 pr-3 font-medium">City (OPA)</th>
              <th scope="col" class="py-2 font-medium">Our model</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in officialCard" :key="row.stat" class="border-b border-line-faint">
              <th scope="row" class="py-2 pr-3 font-normal">{{ row.stat }}</th>
              <td class="py-2 pr-3">{{ row.target }}</td>
              <td class="money py-2 pr-3">{{ row.city }}</td>
              <td class="money py-2">{{ row.ours }}</td>
            </tr>
          </tbody>
        </table>
      </details>

      <details class="mt-3 rounded-md border border-line-faint p-3">
        <summary class="cursor-pointer font-semibold text-brand-600">
          Full table — every arms-length sale, no exclusions
        </summary>
        <table class="mt-3 w-full text-left text-body-sm">
          <caption class="sr-only">Full-sample ratio statistics, city versus our model</caption>
          <thead>
            <tr class="border-b border-line text-muted">
              <th scope="col" class="py-2 pr-3 font-medium">Statistic</th>
              <th scope="col" class="py-2 pr-3 font-medium">Acceptable</th>
              <th scope="col" class="py-2 pr-3 font-medium">City (OPA)</th>
              <th scope="col" class="py-2 font-medium">Our model</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in fullCard" :key="row.stat" class="border-b border-line-faint">
              <th scope="row" class="py-2 pr-3 font-normal">{{ row.stat }}</th>
              <td class="py-2 pr-3">{{ row.target }}</td>
              <td class="money py-2 pr-3">{{ row.city }}</td>
              <td class="money py-2">{{ row.ours }}</td>
            </tr>
          </tbody>
        </table>
        <p class="mt-2 text-caption text-faint">
          Neither passes; ours fails by a fraction of the margin (PRB −0.06 vs −0.23, COD 25.9 vs
          34.5). The gap between the two tables is the 3×IQR trim removing the cash/distressed tail
          — an exclusion built into the official standard itself.
        </p>
      </details>

      <details class="mt-3 rounded-md border border-line-faint p-3">
        <summary class="cursor-pointer font-semibold text-brand-600">Definitions</summary>
        <dl class="mt-3 space-y-2 text-body-sm text-body">
          <div>
            <dt class="font-bold text-ink">Sales ratio</dt>
            <dd>Assessed value ÷ sale price. 1.00 means the assessment matched the market.</dd>
          </div>
          <div>
            <dt class="font-bold text-ink">COD — coefficient of dispersion</dt>
            <dd>Average % spread of ratios around the median. Lower = similar homes treated alike.</dd>
          </div>
          <div>
            <dt class="font-bold text-ink">PRD — price-related differential</dt>
            <dd>Above 1.03 means cheaper homes carry relatively higher assessments (regressive).</dd>
          </div>
          <div>
            <dt class="font-bold text-ink">PRB — price-related bias</dt>
            <dd>
              The preferred regressivity test: % change in ratio as value doubles. Negative =
              regressive; −0.234 means ratios fall ~23% per doubling of value.
            </dd>
          </div>
        </dl>
      </details>

      <p class="mt-4 text-caption text-faint">
        Source: out-of-time test slice of model run 20260705T015912Z, n ≈ 19,500 arms-length
        Philadelphia sales; the sale-chasing check uses the assesspy implementation across
        TY2025–2026. Every figure is reproducible from the
        <a :href="SITE.githubUrl" rel="noopener" class="font-semibold text-brand-600 underline"
          >open-source pipeline</a
        >
        (<code>philly train-baseline</code>, <code>philly ratio-study</code>) and documented — with
        the measurements that did NOT work — in the
        <a :href="SITE.modelDocsUrl" rel="noopener" class="font-semibold text-brand-600 underline"
          >technical model documentation</a
        >.
      </p>
    </SectionCard>

    <p class="text-body-sm text-muted">
      Next:
      <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
        >how the model works</RouterLink
      >
      · or
      <RouterLink to="/" class="font-semibold text-brand-600 underline"
        >check your own home</RouterLink
      >.
    </p>
  </div>
</template>
