<script setup lang="ts">
/** Assessment history line with sale markers.
 * Azure line = the city's assessment through time; gold diamonds = real
 * sales (the chart grammar's "a real-world event" color). */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { line as d3line } from 'd3-shape'
import { money, moneyCompact } from '@/utils/format'
import type { SaleRow, YearValue } from '@/api/types'

const props = defineProps<{ assessments: YearValue[]; sales: SaleRow[] }>()

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

const HEIGHT = 170
const PAD = { left: 8, right: 64, top: 22, bottom: 26 }

const salePoints = computed(() =>
  props.sales
    .filter((s) => s.price != null && s.price > 0)
    .map((s) => ({ year: Number(s.date.slice(0, 4)) + 0.5, value: s.price as number })),
)

const years = computed(() => {
  const ys = [...props.assessments.map((a) => a.year), ...salePoints.value.map((s) => s.year)]
  return ys.length ? ([Math.min(...ys), Math.max(...ys)] as [number, number]) : ([2015, 2026] as [number, number])
})
const values = computed(() => {
  const vs = [...props.assessments.map((a) => a.value), ...salePoints.value.map((s) => s.value)]
  return vs.length ? ([0, Math.max(...vs) * 1.1] as [number, number]) : ([0, 1] as [number, number])
})

const x = computed(() =>
  scaleLinear().domain(years.value).range([PAD.left, width.value - PAD.right]),
)
const y = computed(() =>
  scaleLinear().domain(values.value).range([HEIGHT - PAD.bottom, PAD.top]),
)

const path = computed(() => {
  const gen = d3line<YearValue>()
    .x((d) => x.value(d.year))
    .y((d) => y.value(d.value))
  return gen(props.assessments) ?? ''
})

const last = computed(() => props.assessments[props.assessments.length - 1])

function diamond(cx: number, cy: number, r = 5.5): string {
  return `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`
}

const ariaLabel = computed(() => {
  const first = props.assessments[0]
  if (!first || !last.value) return 'No assessment history available.'
  return (
    `City assessment history from ${first.year} (${money(first.value)}) ` +
    `to ${last.value.year} (${money(last.value.value)}). ` +
    `${salePoints.value.length} recorded sales shown as diamonds.`
  )
})
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
      <!-- baseline hairline -->
      <line
        :x1="PAD.left"
        :x2="width - 8"
        :y1="HEIGHT - PAD.bottom"
        :y2="HEIGHT - PAD.bottom"
        stroke="#dfe5ec"
        stroke-width="1"
      />
      <path :d="path" fill="none" stroke="#0f4d90" stroke-width="2.5" />
      <circle
        v-for="a in props.assessments"
        :key="`a${a.year}`"
        :cx="x(a.year)"
        :cy="y(a.value)"
        r="2.5"
        fill="#0f4d90"
      >
        <title>{{ a.year }} assessment: {{ money(a.value) }}</title>
      </circle>
      <g v-for="s in salePoints" :key="`s${s.year}${s.value}`">
        <path :d="diamond(x(s.year), y(s.value))" fill="#f3c613" stroke="#8a6100" stroke-width="1.5">
          <title>Sold {{ Math.floor(s.year) }} for {{ money(s.value) }}</title>
        </path>
      </g>
      <text
        v-if="last"
        :x="x(last.year) + 8"
        :y="y(last.value) + 4"
        fill="#0f4d90"
        class="text-[12px] font-bold"
      >
        {{ moneyCompact(last.value) }} today
      </text>
      <text :x="PAD.left" :y="HEIGHT - 8" fill="#5d6b7c" class="text-[12px]">
        {{ years[0] }}
      </text>
      <text
        :x="width - PAD.right"
        :y="HEIGHT - 8"
        text-anchor="end"
        fill="#5d6b7c"
        class="text-[12px]"
      >
        {{ Math.floor(years[1]) }}
      </text>
    </svg>
    <p class="mt-1 flex items-center gap-4 text-caption text-muted">
      <span class="inline-flex items-center gap-1.5">
        <span aria-hidden="true" class="inline-block h-0.5 w-5 bg-brand-600"></span> City assessment
      </span>
      <span class="inline-flex items-center gap-1.5">
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M 6 1 L 11 6 L 6 11 L 1 6 Z" fill="#f3c613" stroke="#8a6100" stroke-width="1.2" />
        </svg>
        Actual sale
      </span>
    </p>
  </div>
</template>
