<script setup lang="ts">
/** Interactive teaching graphic for "why a range?": 80 simulated sales of
 * similar homes as dots; a slider changes the confidence level and the band
 * widens or narrows to cover that share of the dots. Deterministic (seeded)
 * so it renders the same for everyone. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { moneyCompact } from '@/utils/format'

const wrapper = ref<HTMLDivElement | null>(null)
const width = ref(560)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width
    if (w) width.value = Math.max(280, w)
  })
  if (wrapper.value) observer.observe(wrapper.value)
})
onBeforeUnmount(() => observer?.disconnect())

// Deterministic pseudo-random sale prices around $300k (log-normal-ish).
function mulberry32(seed: number) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rand = mulberry32(42)
const N = 80
const prices: number[] = Array.from({ length: N }, () => {
  // sum of uniforms ≈ normal; exp() for a right skew like real prices
  const z = rand() + rand() + rand() + rand() - 2
  return 300_000 * Math.exp(z * 0.28)
}).sort((a, b) => a - b)

const level = ref(90)
const levels = [50, 80, 90, 95]

const band = computed<[number, number]>(() => {
  const tail = (1 - level.value / 100) / 2
  const lo = prices[Math.floor(tail * (N - 1))] ?? prices[0]!
  const hi = prices[Math.ceil((1 - tail) * (N - 1))] ?? prices[N - 1]!
  return [lo, hi]
})
const median = prices[Math.floor(N / 2)]!
const covered = computed(
  () => prices.filter((p) => p >= band.value[0] && p <= band.value[1]).length,
)

const HEIGHT = 210
const PAD = { left: 16, right: 16, top: 20, bottom: 40 }
const x = computed(() =>
  scaleLinear()
    .domain([prices[0]! * 0.95, prices[N - 1]! * 1.05])
    .range([PAD.left, width.value - PAD.right]),
)

// Beeswarm-ish stacking: dots in the same little x-bucket pile upward.
const dots = computed(() => {
  const bucketW = 14
  const counts = new Map<number, number>()
  return prices.map((p) => {
    const bucket = Math.round(x.value(p) / bucketW)
    const n = counts.get(bucket) ?? 0
    counts.set(bucket, n + 1)
    return { cx: x.value(p), cy: HEIGHT - PAD.bottom - 8 - n * 13, price: p }
  })
})
</script>

<template>
  <div ref="wrapper" class="w-full">
    <div class="mb-3 flex flex-wrap items-center gap-3">
      <label for="ci-level" class="text-sm font-medium text-slate-800">
        How sure should we be?
      </label>
      <div class="flex gap-1" role="group" aria-labelledby="ci-level">
        <button
          v-for="l in levels"
          :key="l"
          type="button"
          class="min-h-11 rounded-lg px-3.5 text-sm font-semibold"
          :class="
            level === l
              ? 'bg-brand-600 text-white'
              : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          "
          :aria-pressed="level === l"
          @click="level = l"
        >
          {{ l }}%
        </button>
      </div>
    </div>

    <svg
      :width="width"
      :height="HEIGHT"
      :viewBox="`0 0 ${width} ${HEIGHT}`"
      role="img"
      :aria-label="`Eighty example sales of similar homes. A ${level}% range covers ${covered} of the 80 dots, from ${moneyCompact(band[0])} to ${moneyCompact(band[1])}.`"
      class="block w-full"
    >
      <rect
        :x="x(band[0])"
        :y="PAD.top"
        :width="Math.max(0, x(band[1]) - x(band[0]))"
        :height="HEIGHT - PAD.top - PAD.bottom"
        rx="8"
        fill="#bfd3ee"
        opacity="0.55"
        style="transition: all 0.35s ease"
      />
      <circle
        v-for="(d, i) in dots"
        :key="i"
        :cx="d.cx"
        :cy="d.cy"
        r="4.5"
        :fill="d.price >= band[0] && d.price <= band[1] ? '#1e56a0' : '#cbd5e1'"
        style="transition: fill 0.35s ease"
      >
        <title>Sold for {{ moneyCompact(d.price) }}</title>
      </circle>
      <line
        :x1="x(median)"
        :x2="x(median)"
        :y1="PAD.top - 6"
        :y2="HEIGHT - PAD.bottom + 6"
        stroke="#163e75"
        stroke-width="3"
      />
      <text
        :x="x(median)"
        :y="PAD.top - 8"
        text-anchor="middle"
        class="fill-brand-700 text-[13px] font-semibold"
      >
        Best estimate {{ moneyCompact(median) }}
      </text>
      <text :x="x(band[0])" :y="HEIGHT - 14" text-anchor="middle" class="fill-slate-600 text-[12px]">
        {{ moneyCompact(band[0]) }}
      </text>
      <text :x="x(band[1])" :y="HEIGHT - 14" text-anchor="middle" class="fill-slate-600 text-[12px]">
        {{ moneyCompact(band[1]) }}
      </text>
    </svg>

    <p class="mt-2 text-sm text-slate-700" aria-live="polite">
      Each dot is a sale of a similar home. A <strong>{{ level }}%</strong> range covers
      <strong>{{ covered }} of 80</strong> dots — if we made this promise 100 times, we’d expect to
      be right about {{ level }} times. More certainty means a wider range. We use
      <strong>90%</strong> on this site.
    </p>
  </div>
</template>
