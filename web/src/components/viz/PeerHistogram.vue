<script setup lang="ts">
/** Where this home sits among its neighbors: the distribution of
 * (city value ÷ our estimate) for similar homes nearby, with markers for
 * "this home" and the fair line at 1.0. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { pct } from '@/utils/format'
import type { HistBin } from '@/api/types'

const props = defineProps<{
  histogram: HistBin[]
  you: number
  peerMedian: number
}>()

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

const HEIGHT = 190
const PAD = { left: 10, right: 10, top: 34, bottom: 34 }

const domain = computed<[number, number]>(() => {
  const first = props.histogram[0]
  const last = props.histogram[props.histogram.length - 1]
  return first && last ? [first.x0, last.x1] : [0.4, 1.6]
})

const x = computed(() =>
  scaleLinear().domain(domain.value).range([PAD.left, width.value - PAD.right]),
)
const maxN = computed(() => Math.max(1, ...props.histogram.map((b) => b.n)))
const y = computed(() =>
  scaleLinear().domain([0, maxN.value]).range([HEIGHT - PAD.bottom, PAD.top]),
)

const clampedYou = computed(() =>
  Math.min(Math.max(props.you, domain.value[0]), domain.value[1]),
)

const ariaLabel = computed(
  () =>
    `This home is assessed at ${pct(props.you)} of our estimated value. ` +
    `Similar homes nearby sit at ${pct(props.peerMedian)} in the middle.`,
)
</script>

<template>
  <div ref="wrapper" class="w-full">
    <svg
      :width="width"
      :height="HEIGHT"
      :viewBox="`0 0 ${width} ${HEIGHT}`"
      role="img"
      :aria-label="ariaLabel"
      class="block w-full"
    >
      <!-- bars -->
      <rect
        v-for="b in props.histogram"
        :key="b.x0"
        :x="x(b.x0) + 1"
        :y="y(b.n)"
        :width="Math.max(0, x(b.x1) - x(b.x0) - 2)"
        :height="HEIGHT - PAD.bottom - y(b.n)"
        rx="2"
        class="fill-slate-300"
      />

      <!-- fair line at 1.0 -->
      <line
        :x1="x(1)"
        :x2="x(1)"
        :y1="PAD.top - 6"
        :y2="HEIGHT - PAD.bottom"
        stroke="#334155"
        stroke-width="1.5"
        stroke-dasharray="4 3"
      />
      <text :x="x(1)" :y="PAD.top - 12" text-anchor="middle" class="fill-slate-600 text-[12px]">
        Fair (100%)
      </text>

      <!-- this home -->
      <g :transform="`translate(${x(clampedYou)}, 0)`">
        <line
          x1="0"
          x2="0"
          :y1="PAD.top + 8"
          :y2="HEIGHT - PAD.bottom"
          stroke="#163e75"
          stroke-width="3"
        />
        <circle cx="0" :cy="PAD.top + 8" r="5" fill="#163e75" />
        <text
          x="0"
          :y="PAD.top + 0"
          text-anchor="middle"
          class="fill-brand-700 text-[13px] font-semibold"
        >
          Your home {{ pct(props.you) }}
        </text>
      </g>

      <!-- x axis labels -->
      <text :x="PAD.left" :y="HEIGHT - 10" class="fill-slate-500 text-[12px]">
        Assessed low
      </text>
      <text
        :x="width - PAD.right"
        :y="HEIGHT - 10"
        text-anchor="end"
        class="fill-slate-500 text-[12px]"
      >
        Assessed high
      </text>
    </svg>
  </div>
</template>
