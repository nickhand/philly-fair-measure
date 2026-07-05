<script setup lang="ts">
/** Methodology — long-form explainer. Interactive confidence widget:
 * 50/80/90/95% buttons over 80 dots (dots = past sales of homes like yours;
 * filled = sale landed inside the range at that confidence level).
 * TODO before ship: fairness-table figures are SAMPLE values from the design
 * pass — replace with real validation numbers. */
import { computed, ref } from 'vue'

const LEVELS = [50, 80, 90, 95] as const
const level = ref<(typeof LEVELS)[number]>(90)
const TOTAL = 80
const filled = computed(() => Math.round((TOTAL * level.value) / 100))
const dots = computed(() =>
  Array.from({ length: TOTAL }, (_, i) => i < filled.value),
)
</script>

<template>
  <div class="mx-auto max-w-2xl px-4 py-6 sm:py-8">
    <p class="text-[11px] font-bold uppercase tracking-[0.1em] text-brand-600">Methodology</p>
    <h1 class="mt-2 font-display text-[28px] font-bold leading-tight text-ink sm:text-[34px]">How this works</h1>
    <p class="mt-2.5 text-[14.5px] leading-relaxed text-body">
      We build an independent estimate of what each Philadelphia home is worth, using the same
      public records the city uses. Then we compare our estimate with the city’s assessment.
    </p>

    <!-- confidence widget -->
    <section class="mt-5 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <h2 class="text-[15.5px] font-bold text-ink">What does “90% sure” mean?</h2>
      <p class="mt-1 text-[13px] leading-relaxed text-muted">
        Each dot is a home like yours that sold. Pick a confidence level — the range grows or
        shrinks so that many dots land inside it.
      </p>
      <div class="mt-3.5 flex gap-1.5" role="group" aria-label="Confidence level">
        <button
          v-for="l in LEVELS"
          :key="l"
          type="button"
          class="h-10 flex-1 rounded-md border-[1.5px] text-[13.5px] font-bold transition-colors duration-[var(--duration-fast)]"
          :class="level === l ? 'border-brand-600 bg-brand-600 text-white' : 'border-[#b8c4d2] text-body hover:bg-brand-50'"
          :aria-pressed="level === l"
          @click="level = l"
        >
          {{ l }}%
        </button>
      </div>
      <div
        class="mt-4 flex flex-wrap justify-center gap-[11px] px-2"
        role="img"
        :aria-label="`${filled} of ${TOTAL} homes sold inside the range at the ${level}% confidence level.`"
      >
        <span
          v-for="(isFilled, i) in dots"
          :key="i"
          class="h-[11px] w-[11px] rounded-full"
          :class="isFilled ? 'bg-brand-600' : 'border-[1.5px] border-brand-300 bg-white'"
          aria-hidden="true"
        ></span>
      </div>
      <p class="mt-3 text-center text-[12.5px] leading-normal text-body">
        <strong class="text-brand-600">{{ filled }} of {{ TOTAL }}</strong> sold inside the range —
        <span class="text-muted">open dots are the misses no honest model can avoid.</span>
      </p>
    </section>

    <!-- fairness table -->
    <section class="mt-4 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <h2 class="text-[15.5px] font-bold text-ink">How our estimates hold up</h2>
      <p class="mt-1 text-[12.5px] text-muted">Checked against real sales the model never saw. <em>(sample figures)</em></p>
      <table class="mt-3 w-full text-left text-[13px]">
        <caption class="sr-only">Model accuracy compared with city assessments</caption>
        <thead>
          <tr class="border-b border-line text-muted">
            <th scope="col" class="py-1.5 pr-2 font-semibold"></th>
            <th scope="col" class="py-1.5 pr-2 font-semibold">Our model</th>
            <th scope="col" class="py-1.5 font-semibold">City values</th>
          </tr>
        </thead>
        <tbody class="text-body">
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-2 pr-2 font-normal leading-snug">Typical miss vs. actual sale price</th>
            <td class="py-2 pr-2 font-bold tabular-nums text-ink">9%</td>
            <td class="py-2 tabular-nums">15%</td>
          </tr>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-2 pr-2 font-normal leading-snug">Sales landing inside our stated range</th>
            <td class="py-2 pr-2 font-bold tabular-nums text-ink">90 of 100</td>
            <td class="py-2">no range given</td>
          </tr>
          <tr>
            <th scope="row" class="py-2 pr-2 font-normal leading-snug">Cheaper homes treated same as pricier ones</th>
            <td class="py-2 pr-2 font-bold text-ink">Yes</td>
            <td class="py-2">Uneven</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- honesty section -->
    <section class="mt-4 rounded-xl border border-gold-border bg-gold-soft p-4 sm:p-5">
      <div class="flex items-start gap-2.5">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#8a6100" stroke-width="2" stroke-linecap="round" aria-hidden="true" class="mt-0.5 shrink-0"><circle cx="12" cy="12" r="9.5" /><line x1="12" y1="11" x2="12" y2="16.5" /><circle cx="12" cy="7.5" r="0.6" fill="#8a6100" /></svg>
        <div>
          <h2 class="text-[15.5px] font-bold text-gold-700">What we cannot see</h2>
          <p class="mt-1.5 text-[13px] leading-relaxed text-[#4d4633]">
            Public records don’t show a renovated kitchen, a leaking roof, or anything else inside
            your walls. If the inside of your home differs a lot from its records, our estimate can
            be wrong — in either direction. That is why every report shows a range, and why the
            facts table matters more than any single number.
          </p>
        </div>
      </div>
    </section>

    <p class="mt-4 text-[11.5px] leading-normal text-faint">
      Data updated 2026-07-04 · Model code and validation are public · Independent — not a City of
      Philadelphia site
    </p>
  </div>
</template>
