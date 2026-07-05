<script setup lang="ts">
/** HistorySpark — the city's value over time, with real sales as gold
 * diamonds (gold = a real-world event, per the chart grammar).
 *
 * Only arms-length sales are PLOTTED: $1 family transfers and other nominal
 * deeds would crush the y-scale and mislead (the "Recorded sales" list below
 * the chart still shows every deed, annotated). Labels are line-aware and
 * clamped so they never collide with the assessment line, the "today" label,
 * or the plot edges. */
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
    .filter((s) => s.price != null && s.price > 0 && s.validity === 'arms_length')
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

/** Assessment-line height at an arbitrary year (linear interpolation) — used
 * to keep sale labels off the line. */
function lineYAt(year: number): number | null {
  const pts = props.assessments
  if (!pts.length) return null
  if (year <= pts[0]!.year) return y.value(pts[0]!.value)
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]!
    const b = pts[i]!
    if (year <= b.year) {
      const t = (year - a.year) / Math.max(1e-9, b.year - a.year)
      return y.value(a.value + t * (b.value - a.value))
    }
  }
  return y.value(pts[pts.length - 1]!.value)
}

function saleAnchor(sx: number): 'start' | 'middle' | 'end' {
  if (sx < PAD + 50) return 'start'
  if (sx > width.value - PAD - 50) return 'end'
  return 'middle'
}

/** Place each sale label above its diamond unless that spot is (a) off the top
 * of the plot, (b) within a band of the assessment line, or (c) colliding with
 * the "today" label — then drop it below the diamond. */
function saleLabelY(sx: number, sy: number, year: number): number {
  const above = sy - 12
  let collide = above < 11 // clipped at the top edge
  const ly = lineYAt(year)
  if (ly != null && Math.abs(above - ly) < 11) collide = true
  if (last.value) {
    const lx = x.value(last.value.year)
    const ty = y.value(last.value.value) - 8
    if (Math.abs(sx - lx) < 110 && Math.abs(above - ty) < 14) collide = true
  }
  return collide ? Math.min(BASE - 2, sy + 22) : above
}

const ariaLabel = computed(() => {
  const first = props.assessments[0]
  if (!first || !last.value) return 'No assessment history available.'
  let s = `The city's assessment went from ${moneyCompact(first.value)} in ${first.year} to ${moneyCompact(last.value.value)} in ${last.value.year}.`
  for (const sale of pricedSales.value)
    s += ` The home sold for ${moneyCompact(sale.price as number)} in ${sale.year}.`
  return s
})

/** Hover/touch readout: snap to the nearest assessment year and show its
 * value (plus the sale, if one happened that year). Purely transient — the
 * aria description and the "Recorded sales" list carry the non-visual path. */
const hover = ref<{ year: number; value: number; sale: number | null; sx: number; sy: number } | null>(
  null,
)

function onMove(e: PointerEvent) {
  const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
  const yr = x.value.invert(e.clientX - rect.left)
  let best: YearValue | undefined
  for (const a of props.assessments)
    if (!best || Math.abs(a.year - yr) < Math.abs(best.year - yr)) best = a
  if (!best) return
  const b = best
  const sale = pricedSales.value.find((s) => s.year === b.year)
  hover.value = {
    year: b.year,
    value: b.value,
    sale: sale ? (sale.price as number) : null,
    sx: x.value(b.year),
    sy: y.value(b.value),
  }
}
</script>

<template>
  <div ref="wrapper" class="relative w-full">
    <svg
      :width="width" :height="HEIGHT" :viewBox="`0 0 ${width} ${HEIGHT}`" role="img"
      :aria-label="ariaLabel" class="block w-full touch-none font-sans"
      @pointermove="onMove" @pointerdown="onMove" @pointerleave="hover = null"
    >
      <line :x1="PAD" :y1="BASE" :x2="width - PAD" :y2="BASE" stroke="#dfe5ec" stroke-width="1" />
      <path :d="path" fill="none" stroke="#0f4d90" stroke-width="2.5" stroke-linecap="round" />
      <template v-if="hover">
        <line :x1="hover.sx" :y1="TOP" :x2="hover.sx" :y2="BASE" stroke="#c6d0dc" stroke-width="1" aria-hidden="true" />
        <circle :cx="hover.sx" :cy="hover.sy" r="3.5" fill="#ffffff" stroke="#0f4d90" stroke-width="2" aria-hidden="true" />
      </template>
      <template v-if="last">
        <circle :cx="x(last.year)" :cy="y(last.value)" r="4" fill="#0f4d90" />
        <text :x="x(last.year)" :y="Math.max(11, y(last.value) - 8)" text-anchor="end" font-size="12.5" font-weight="700" fill="#0f4d90" style="font-variant-numeric: tabular-nums">
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
          :y="saleLabelY(x(s.year), y(s.price as number), s.year)"
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
    <div
      v-if="hover"
      aria-hidden="true"
      class="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-line bg-white px-2 py-1 text-caption shadow-popover"
      :style="{
        left: `${Math.min(Math.max(hover.sx, 72), width - 72)}px`,
        top: `${Math.max(0, hover.sy - 34)}px`,
      }"
    >
      <span class="font-bold text-ink tabular-nums">{{ hover.year }}</span>
      <span class="text-body tabular-nums"> · assessed {{ moneyCompact(hover.value) }}</span>
      <span v-if="hover.sale != null" class="font-semibold text-[#8a6100] tabular-nums">
        · sold {{ moneyCompact(hover.sale) }}</span
      >
    </div>
  </div>
</template>
