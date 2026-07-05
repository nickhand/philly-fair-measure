<script setup lang="ts">
/** PeerHistogram — assessment ratio vs. similar homes.
 * Chart grammar: azure = peers/our model (solid median line); the orange
 * treatment marks *your* position (dashed line + dot) and your bin.
 * Handoff template merged onto our real bin contract (HistBin {x0,x1,n});
 * `youHex` kept as an optional prop (defaults to the mock's orange). */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { pct } from '@/utils/format'
import type { HistBin } from '@/api/types'

const props = withDefaults(
  defineProps<{
    histogram: HistBin[]
    you: number
    peerMedian: number
    youHex?: string
  }>(),
  { youHex: '#c2410c' },
)

const wrapper = ref<HTMLDivElement | null>(null)
const width = ref(343)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width
    if (w) width.value = Math.max(280, w)
  })
  if (wrapper.value) observer.observe(wrapper.value)
})
onBeforeUnmount(() => observer?.disconnect())

const HEIGHT = 128
const PAD = 24
const BASE = 88
const MAXBAR = 60

const domain = computed(() => {
  const lo = Math.min(...props.histogram.map((b) => b.x0), props.you)
  const hi = Math.max(...props.histogram.map((b) => b.x1), props.you)
  return [lo, hi] as const
})
const x = computed(() =>
  scaleLinear().domain(domain.value).range([PAD, width.value - PAD]),
)
const maxCount = computed(() => Math.max(1, ...props.histogram.map((b) => b.n)))
const barH = (c: number) => (c / maxCount.value) * MAXBAR
const youBin = computed(() =>
  props.histogram.findIndex((b) => props.you >= b.x0 && props.you < b.x1),
)
const ticks = computed(() =>
  [0.7, 1.0, 1.3].filter((t) => t >= domain.value[0] && t <= domain.value[1]),
)

const ariaLabel = computed(
  () =>
    `This home is assessed at ${pct(props.you)} of our estimated value. ` +
    `The middle for similar homes is ${pct(props.peerMedian)}.`,
)
</script>

<template>
  <div ref="wrapper" class="w-full">
    <svg :width="width" :height="HEIGHT" :viewBox="`0 0 ${width} ${HEIGHT}`" role="img" :aria-label="ariaLabel" class="block w-full font-sans">
      <rect
        v-for="(b, i) in histogram"
        :key="b.x0"
        :x="x(b.x0) + 2"
        :y="BASE - barH(b.n)"
        :width="Math.max(2, x(b.x1) - x(b.x0) - 4)"
        :height="barH(b.n)"
        rx="1.5"
        :fill="i === youBin ? '#ffd9bd' : '#c9d9ec'"
      />
      <line :x1="x(peerMedian)" y1="24" :x2="x(peerMedian)" :y2="BASE" stroke="#0f4d90" stroke-width="2" />
      <text
        :x="Math.max(PAD - 14, Math.min(x(peerMedian) - 5, width - 175))"
        y="14"
        text-anchor="start"
        font-size="12.5"
        font-weight="700"
        fill="#0f4d90"
      >
        Similar homes' middle {{ pct(peerMedian) }}
      </text>
      <line :x1="x(you)" y1="34" :x2="x(you)" :y2="BASE" :stroke="youHex" stroke-width="2" stroke-dasharray="3 4" />
      <circle :cx="x(you)" cy="34" r="3.5" :fill="youHex" />
      <text :x="x(you) + 9 > width - 70 ? x(you) - 9 : x(you) + 9" y="30" :text-anchor="x(you) + 9 > width - 70 ? 'end' : 'start'" font-size="12.5" font-weight="700" :fill="youHex">
        You {{ pct(you) }}
      </text>
      <line :x1="PAD" :y1="BASE" :x2="width - PAD" :y2="BASE" stroke="#dfe5ec" stroke-width="1" />
      <text v-for="t in ticks" :key="t" :x="x(t)" :y="BASE + 15" text-anchor="middle" font-size="11.5" fill="#8593a4" style="font-variant-numeric: tabular-nums">
        {{ Math.round(t * 100) }}%
      </text>
      <text :x="width / 2" :y="HEIGHT - 4" text-anchor="middle" font-size="11.5" fill="#8593a4">
        assessment as % of our estimate
      </text>
    </svg>

    <details class="mt-1">
      <summary class="cursor-pointer text-body-sm font-medium text-brand-600">See these numbers as a table</summary>
      <table class="mt-2 w-full max-w-md text-left text-body-sm">
        <caption class="sr-only">Assessment ratio compared with similar homes</caption>
        <tbody>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">This home</th>
            <td class="py-1.5 font-semibold">{{ pct(you) }}</td>
          </tr>
          <tr>
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">Middle of similar homes</th>
            <td class="py-1.5 font-semibold">{{ pct(peerMedian) }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>
</template>
