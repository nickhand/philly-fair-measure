<script setup lang="ts">
/** The transparency page. Written at an 8th-grade level on purpose; every
 * section says what we do, what we can't do, and where the numbers come from. */
import IntervalExplainer from '@/components/viz/IntervalExplainer.vue'
import SectionCard from '@/components/ui/SectionCard.vue'

// Measured on financed (regular-mortgage) sales, out-of-time test — see
// docs/vertical-equity-report-card.md in the repository.
const fairness = [
  { who: 'Cheapest fifth of homes', city: 1.26, ours: 1.03 },
  { who: 'Priciest fifth of homes', city: 0.88, ours: 0.94 },
]
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6 px-4 py-8">
    <div>
      <h1 class="text-3xl font-extrabold text-slate-900">How this works</h1>
      <p class="mt-3 text-lg text-slate-700">
        Everything here is built from the city’s own public data, and everything we do is open. No
        secret sauce — this page explains it all.
      </p>
    </div>

    <SectionCard title="What a property assessment is">
      <p class="text-slate-700">
        Every year, Philadelphia’s Office of Property Assessment (OPA) estimates what your home is
        worth. Your property tax is about <strong>1.4%</strong> of that number. If the number is too
        high, you pay too much tax. If your neighbor’s is too low, they pay too little — and
        everyone else covers the difference.
      </p>
    </SectionCard>

    <SectionCard title="Where our numbers come from">
      <ul class="list-disc space-y-2 pl-5 text-slate-700">
        <li>
          <strong>More than 200,000 real home sales</strong> from city deed records (2016 to today).
        </li>
        <li><strong>City property records</strong> — size, age, style, condition on file.</li>
        <li>
          <strong>City licenses and inspections</strong> — permits, complaints, violations, vacancy.
        </li>
        <li><strong>Public maps</strong> — parcel shapes, transit, parks.</li>
      </ul>
      <p class="mt-3 text-slate-700">
        A computer model learns from those sales: what did homes like this one actually sell for?
        Then it estimates today’s value for every home in the city — the same way the city’s own
        mass-appraisal works, but independent, and with our work shown.
      </p>
      <p class="mt-3 text-slate-700">
        <strong>What we never use:</strong> race, income, or anything about the people who live in a
        home. We check the model for fairness across neighborhoods, but people-data is never part of
        the price.
      </p>
    </SectionCard>

    <SectionCard title="Why we show a range, not just one number">
      <IntervalExplainer />
      <p class="mt-3 text-slate-700">
        We only say “your assessment may be too high” when the city’s value falls
        <strong>outside</strong> the 90% range — and two different statistical methods have to agree
        before we flag it.
      </p>
    </SectionCard>

    <SectionCard title="Is the system fair? The pattern we found">
      <p class="text-slate-700">
        Across the country, cheaper homes tend to be <strong>over</strong>-assessed and expensive
        homes <strong>under</strong>-assessed. Philadelphia is no exception. Here is the pattern on
        recent regular sales — 100% means assessments match sale prices:
      </p>
      <table class="mt-4 w-full text-left text-sm">
        <caption class="sr-only">
          Assessment level by home-value group, city versus our model
        </caption>
        <thead>
          <tr class="border-b border-slate-200 text-slate-600">
            <th scope="col" class="py-2 pr-3 font-medium">Homes</th>
            <th scope="col" class="py-2 pr-3 font-medium">City assessments</th>
            <th scope="col" class="py-2 font-medium">Our model</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in fairness" :key="row.who" class="border-b border-slate-100">
            <th scope="row" class="py-2 pr-3 font-normal">{{ row.who }}</th>
            <td class="py-2 pr-3">
              <span class="font-semibold" :class="row.city > 1.05 ? 'text-over' : ''">
                {{ Math.round(row.city * 100) }}%
              </span>
              <span v-if="row.city > 1.05" class="text-slate-500"> — over-assessed</span>
            </td>
            <td class="py-2 font-semibold">{{ Math.round(row.ours * 100) }}%</td>
          </tr>
        </tbody>
      </table>
      <p class="mt-3 text-sm text-slate-600">
        Measured on regular mortgage-financed sales the model had never seen. Our model isn’t
        perfect either — but it cuts that unfairness roughly in half, which is why a second opinion
        matters.
      </p>
    </SectionCard>

    <SectionCard title="What our model cannot see">
      <ul class="list-disc space-y-2 pl-5 text-slate-700">
        <li>
          <strong>The inside of your home.</strong> City data doesn’t know about your new kitchen —
          or your water damage. Neither do we. That’s the single biggest blind spot, for the city
          and for us.
        </li>
        <li>
          <strong>Very unusual properties.</strong> When a home is unlike anything that sells
          nearby, our range gets wide — and we say so instead of pretending.
        </li>
        <li>
          <strong>Single-home certainty.</strong> A model can be right on average and still wrong
          about one specific house. That is why every report shows the facts, not just a verdict.
        </li>
      </ul>
    </SectionCard>

    <SectionCard title="Who made this">
      <p class="text-slate-700">
        This is an independent, open project — not a city service. The full methodology, code, and
        every measurement (including the ones that didn’t work) are documented in the project
        repository. If you find a mistake, we want to know.
      </p>
    </SectionCard>
  </div>
</template>
