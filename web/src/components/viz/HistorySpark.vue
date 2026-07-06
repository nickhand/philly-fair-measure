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
  // seed from the live layout so the first paint is right even where
  // ResizeObserver is unavailable or never fires (some embedded WebViews)
  if (wrapper.value?.clientWidth) width.value = Math.max(280, wrapper.value.clientWidth)
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
 * to keep sale labels off the line. Null outside the drawn span: a label next
 * to a pre-history sale must not dodge a line that isn't there. */
function lineYAt(year: number): number | null {
  const pts = props.assessments
  if (!pts.length) return null
  if (year < pts[0]!.year || year > pts[pts.length - 1]!.year) return null
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

/** Generic label placement: every label (the "today" callout and each sale)
 * starts above its point and shifts vertically in steps until it clears the
 * labels already placed, the markers, and the assessment line — instead of
 * the previous pairwise special cases, which still let dense charts collide. */
interface PlacedLabel {
  key: string
  text: string
  x: number
  y: number
  anchor: 'start' | 'middle' | 'end'
  fill: string
  weight: number
  size: number
  /** Draw a white plate behind this label — the "today" callout is the same
   * blue as the assessment line and can sit right on it. */
  bg?: boolean
}

const CHAR_W = 6.9
const LABEL_H = 13

function labelRect(l: { x: number; y: number; anchor: string; text: string }) {
  const w = l.text.length * CHAR_W
  const x0 = l.anchor === 'start' ? l.x : l.anchor === 'end' ? l.x - w : l.x - w / 2
  return { x0, x1: x0 + w, y0: l.y - LABEL_H + 2, y1: l.y + 2 }
}

const labels = computed<PlacedLabel[]>(() => {
  type Rect = { x0: number; x1: number; y0: number; y1: number }
  const placed: PlacedLabel[] = []
  const markers: { mx: number; my: number }[] = []
  if (last.value) {
    markers.push({ mx: x.value(last.value.year), my: y.value(last.value.value) })
  }
  for (const s of pricedSales.value) {
    markers.push({ mx: x.value(s.year), my: y.value(s.price as number) })
  }
  // A label may sit snugly above/beside ITS OWN marker (the visual
  // convention) but must clear other markers by a wide berth — so the own
  // marker shrinks to a tight core instead of the full exclusion zone.
  const markerRect = (m: { mx: number; my: number }, own: boolean): Rect => {
    const r = own ? 4 : 9
    return { x0: m.mx - r, x1: m.mx + r, y0: m.my - r, y1: m.my + r }
  }
  // 2px clearance margin: touching rects read as overlapping at dot scale
  const overlaps = (a: Rect, b: Rect) =>
    a.x0 < b.x1 + 2 && b.x0 < a.x1 + 2 && a.y0 < b.y1 + 2 && b.y0 < a.y1 + 2
  const conflicts = (cand: PlacedLabel, ownIdx: number): number => {
    const r = labelRect(cand)
    let n = placed.filter((p) => overlaps(r, labelRect(p))).length
    n += markers.filter((m, i) => overlaps(r, markerRect(m, i === ownIdx))).length
    // the assessment line, sampled at the label's center
    const ly = lineYAt(x.value.invert((r.x0 + r.x1) / 2))
    if (ly != null && r.y0 < ly + 4 && ly - 4 < r.y1) n += 1
    return n
  }
  const place = (cand: PlacedLabel, markerX: number, markerY: number, ownIdx: number) => {
    // candidates: natural spot, then beside the marker (dense chart tops
    // often leave no vertical slot), each swept over clamped y offsets; if
    // nothing is fully clear, take the least-conflicted spot
    const beside = { y: markerY + 4, weight: cand.weight, size: cand.size }
    const bases: PlacedLabel[] = [
      cand,
      { ...cand, ...beside, anchor: 'end', x: markerX - 12 },
      { ...cand, ...beside, anchor: 'start', x: markerX + 12 },
    ]
    let best: PlacedLabel | null = null
    let bestScore = Infinity
    for (const base of bases) {
      for (const dy of [0, 15, -15, 30, -30, 45, -45, 60, -60]) {
        const attempt = { ...base, y: Math.min(BASE - 2, Math.max(11, base.y + dy)) }
        const score = conflicts(attempt, ownIdx)
        if (score === 0) {
          placed.push(attempt)
          return
        }
        if (score < bestScore) {
          best = attempt
          bestScore = score
        }
      }
    }
    placed.push(best ?? cand)
  }
  let markerIdx = 0
  if (last.value) {
    const lx = x.value(last.value.year)
    const ly = y.value(last.value.value)
    place(
      {
        key: 'today',
        text: `${moneyCompact(last.value.value)} today`,
        x: lx,
        y: Math.max(11, ly - 8),
        anchor: 'end',
        fill: '#0f4d90',
        weight: 700,
        size: 12.5,
        bg: true,
      },
      lx,
      ly,
      markerIdx,
    )
    markerIdx += 1
  }
  for (const s of pricedSales.value) {
    const sx = x.value(s.year)
    const sy = y.value(s.price as number)
    place(
      {
        key: `sale-${s.date}`,
        text: `Sold ${moneyCompact(s.price as number)}`,
        x: sx,
        y: sy - 12,
        anchor: saleAnchor(sx),
        fill: '#8a6100',
        weight: 600,
        size: 12,
      },
      sx,
      sy,
      markerIdx,
    )
    markerIdx += 1
  }
  return placed
})

/** White plates behind flagged labels (see PlacedLabel.bg), padded a hair
 * around the estimated text box. */
const labelPlates = computed(() =>
  labels.value
    .filter((l) => l.bg)
    .map((l) => {
      const r = labelRect(l)
      return { key: l.key, x: r.x0 - 3, y: r.y0 - 1, width: r.x1 - r.x0 + 6, height: r.y1 - r.y0 + 2 }
    }),
)

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
      <circle v-if="last" :cx="x(last.year)" :cy="y(last.value)" r="4" fill="#0f4d90" />
      <rect
        v-for="s in pricedSales"
        :key="s.date"
        :x="x(s.year) - 4.5" :y="y(s.price as number) - 4.5" width="9" height="9"
        fill="#ffffff" stroke="#8a6100" stroke-width="2"
        :transform="`rotate(45 ${x(s.year)} ${y(s.price as number)})`"
      />
      <!-- labels last so they paint above markers; positions come from the
           collision solver. White plates sit under flagged labels so a label
           that lands on the same-colored assessment line stays readable. -->
      <rect
        v-for="p in labelPlates"
        :key="`plate-${p.key}`"
        :x="p.x"
        :y="p.y"
        :width="p.width"
        :height="p.height"
        rx="3"
        fill="#ffffff"
        opacity="0.9"
      />
      <text
        v-for="l in labels"
        :key="l.key"
        :x="l.x"
        :y="l.y"
        :text-anchor="l.anchor"
        :font-size="l.size"
        :font-weight="l.weight"
        :fill="l.fill"
        style="font-variant-numeric: tabular-nums"
      >
        {{ l.text }}
      </text>
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
