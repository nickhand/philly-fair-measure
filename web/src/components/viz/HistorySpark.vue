<script setup lang="ts">
/** HistorySpark — the city's value over time, with real sales as gold
 * diamonds (gold = a real-world event, per the chart grammar).
 * Handoff template on our real types (YearValue[], SaleRow[]); the parent
 * guards for assessments.length > 1 before rendering. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { moneyCompact } from '@/utils/format'
import type { SaleRow, YearValue } from '@/api/types'

const props = defineProps<{
  assessments: YearValue[]
  sales: SaleRow[]
}>()

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

const HEIGHT = 118
const PAD = 18
const TOP = 14
const BASE = 90

const pricedSales = computed(() =>
  props.sales
    .filter((s) => s.price != null && s.price > 0)
    .map((s) => ({ ...s, year: Number(s.date.slice(0, 4)) })),
)
const years = computed(() => {
  const ys = props.assessments.map((a) => a.year).concat(pricedSales.value.map((s) => s.year))
  return [Math.min(...ys), Math.max(...ys)] as const
})
const values = computed(() => {
  const vs = props.assessments
    .map((a) => a.value)
    .concat(pricedSales.value.map((s) => s.price as number))
  return [Math.min(...vs), Math.max(...vs)] as const
})
const x = computed(() => scaleLinear().domain(years.value).range([PAD, width.value - PAD]))
const y = computed(() => scaleLinear().domain(values.value).range([BASE - 8, TOP + 4]))

const path = computed(() =>
  props.assessments
    .map((a, i) => `${i === 0 ? 'M' : 'L'} ${x.value(a.year)} ${y.value(a.value)}`)
    .join(' '),
)
const last = computed(() => props.assessments[props.assessments.length - 1])

/** Sale labels: flip the anchor near either edge so text never clips, and
 * drop below the diamond when it would collide with the "today" label. */
function saleAnchor(sx: number): 'start' | 'middle' | 'end' {
  if (sx < PAD + 50) return 'start'
  if (sx > width.value - PAD - 50) return 'end'
  return 'middle'
}
function saleLabelY(sx: number, sy: number): number {
  if (!last.value) return sy - 12
  const lx = x.value(last.value.year)
  const ly = y.value(last.value.value)
  const collides = Math.abs(sx - lx) < 110 && Math.abs(sy - 12 - (ly - 8)) < 16
  return collides ? sy + 22 : sy - 12
}

const ariaLabel = computed(() => {
  const first = props.assessments[0]
  if (!first || !last.value) return 'No assessment history available.'
  let s = `The city's assessment went from ${moneyCompact(first.value)} in ${first.year} to ${moneyCompact(last.value.value)} in ${last.value.year}.`
  for (const sale of pricedSales.value)
    s += ` The home sold for ${moneyCompact(sale.price as number)} in ${sale.year}.`
  return s
})
</script>

<template>
  <div ref="wrapper" class="w-full">
    <svg :width="width" :height="HEIGHT" :viewBox="`0 0 ${width} ${HEIGHT}`" role="img" :aria-label="ariaLabel" class="block w-full font-sans">
      <line :x1="PAD" :y1="BASE" :x2="width - PAD" :y2="BASE" stroke="#dfe5ec" stroke-width="1" />
      <path :d="path" fill="none" stroke="#0f4d90" stroke-width="2.5" stroke-linecap="round" />
      <template v-if="last">
        <circle :cx="x(last.year)" :cy="y(last.value)" r="4" fill="#0f4d90" />
        <text :x="x(last.year)" :y="y(last.value) - 8" text-anchor="end" font-size="12.5" font-weight="700" fill="#0f4d90" style="font-variant-numeric: tabular-nums">
          {{ moneyCompact(last.value) }} today
        </text>
      </template>
      <g v-for="s in pricedSales" :key="s.date">
        <rect
          :x="x(s.year) - 4.5" :y="y(s.price as number) - 4.5" width="9" height="9"
          fill="#ffffff" stroke="#8a6100" stroke-width="2"
          :transform="`rotate(45 ${x(s.year)} ${y(s.price as number)})`"
        />
        <text
          :x="x(s.year)"
          :y="saleLabelY(x(s.year), y(s.price as number))"
          :text-anchor="saleAnchor(x(s.year))"
          font-size="12"
          font-weight="600"
          fill="#8a6100"
          style="font-variant-numeric: tabular-nums"
        >
          Sold {{ moneyCompact(s.price as number) }}
        </text>
      </g>
      <text :x="PAD" :y="BASE + 15" text-anchor="start" font-size="11.5" fill="#8593a4">{{ years[0] }}</text>
      <text :x="width - PAD" :y="BASE + 15" text-anchor="end" font-size="11.5" fill="#8593a4">{{ years[1] }}</text>
    </svg>
  </div>
</template>
