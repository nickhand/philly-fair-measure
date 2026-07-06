<script setup lang="ts">
/** The core explanatory graphic, restyled (Flag & Ledger). All geometry,
 * ResizeObserver, ARIA and <details> fallback logic preserved from the
 * original component — only the visual treatment changed:
 *  band #dbe7f5 / #b9d2ee · estimate tick + label azure #0f4d90 ·
 *  city marker (triangle + dashed drop + dot) in verdict.hex ·
 *  caption "range we're 90% sure about".
 * For within_range the estimate label flips below the band so it never
 * collides with the city label. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { money, moneyCompact } from '@/utils/format'
import { verdictFor } from '@/utils/verdict'
import type { Flag } from '@/api/types'

const props = defineProps<{
  low: number
  high: number
  median: number
  opa: number
  flag: Flag
}>()

const wrapper = ref<HTMLDivElement | null>(null)
const width = ref(640)
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

const PAD = 18
const BAND_Y = 72
const BAND_H = 24

const x = computed(() => {
  const lo = Math.min(props.low, props.opa) * 0.94
  const hi = Math.max(props.high, props.opa) * 1.06
  return scaleLinear().domain([lo, hi]).range([PAD, width.value - PAD])
})

const verdict = computed(() => verdictFor(props.flag))
const inside = computed(() => props.flag === 'within_range')
const opaX = computed(() => x.value(props.opa))
const opaLabelAnchor = computed(() => {
  const frac = (opaX.value - PAD) / Math.max(1, width.value - 2 * PAD)
  return frac < 0.18 ? 'start' : frac > 0.82 ? 'end' : 'middle'
})

/** Phone-width layout: the full label strings ("City value …", "Our
 * estimate …") plus the bound labels need ~450px before they stop colliding
 * or running off the edges, so below that the labels shorten and the bounds
 * move into the caption line. */
const narrow = computed(() => width.value < 460)
const cityLabel = computed(
  () => `${narrow.value ? 'City' : 'City value'} ${moneyCompact(props.opa)}`,
)
const estLabel = computed(
  () => `${narrow.value ? 'Ours' : 'Our estimate'} ${moneyCompact(props.median)}`,
)
const caption = computed(() =>
  narrow.value
    ? `range we're 90% sure about: ${moneyCompact(props.low)}–${moneyCompact(props.high)}`
    : "range we're 90% sure about",
)
/** Narrow gets a taller canvas: the within-range estimate label sits below
 * the band there, and at 140px it runs into the caption row. */
const height = computed(() => (narrow.value ? 152 : 140))

/** Estimate label: flip anchor near the chart edges (no cut-off text), and
 * when the city marker is close, slide to the far side of its drop line so
 * the dashed line never strikes through the label. */
const medX = computed(() => x.value(props.median))
const estAnchor = computed<'start' | 'middle' | 'end'>(() => {
  const frac = (medX.value - PAD) / Math.max(1, width.value - 2 * PAD)
  if (frac < 0.15) return 'start'
  if (frac > 0.85) return 'end'
  if (Math.abs(medX.value - opaX.value) < (narrow.value ? 80 : 95)) {
    // far side of the city drop line — unless that side runs into the
    // low/high bound labels at the strip's edges, then take the near side
    const farSide = medX.value <= opaX.value ? 'end' : 'start'
    if (farSide === 'end' && frac < 0.28) return 'start'
    if (farSide === 'start' && frac > 0.72) return 'end'
    return farSide
  }
  return 'middle'
})
const estLabelX = computed(() => {
  if (estAnchor.value === 'start') return medX.value + 8
  if (estAnchor.value === 'end') return medX.value - 8
  return medX.value
})

const ariaLabel = computed(
  () =>
    `Our model estimates this home is worth between ${money(props.low)} and ${money(props.high)}, ` +
    `with a best estimate of ${money(props.median)}. The city's value is ${money(props.opa)}, ` +
    `which is ${props.flag === 'within_range' ? 'inside' : 'outside'} that range.`,
)
</script>

<template>
  <div ref="wrapper" class="w-full">
    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="ariaLabel"
      class="block w-full font-sans"
    >
      <!-- city value marker (reads first) -->
      <g :transform="`translate(${opaX}, 0)`">
        <text
          :text-anchor="opaLabelAnchor"
          :x="opaLabelAnchor === 'end' ? 10 : opaLabelAnchor === 'start' ? -10 : 0"
          y="14"
          :font-size="narrow ? 13 : 14"
          font-weight="700"
          :fill="verdict.hex"
          style="font-variant-numeric: tabular-nums"
        >
          {{ cityLabel }}
        </text>
        <path d="M 0 22 L 6 31 L -6 31 Z" :fill="verdict.hex" />
        <line x1="0" x2="0" y1="31" :y2="BAND_Y + BAND_H + 6" :stroke="verdict.hex" stroke-width="2" stroke-dasharray="3 4" />
        <circle cx="0" :cy="BAND_Y + BAND_H + 10" r="3.5" :fill="verdict.hex" />
      </g>

      <!-- the 90% band -->
      <rect
        class="band"
        :x="x(props.low)"
        :y="BAND_Y"
        :width="Math.max(0, x(props.high) - x(props.low))"
        :height="BAND_H"
        rx="5"
        fill="#dbe7f5"
        stroke="#b9d2ee"
      />
      <!-- best estimate tick -->
      <line
        :x1="x(props.median)"
        :x2="x(props.median)"
        :y1="BAND_Y - 9"
        :y2="BAND_Y + BAND_H + 9"
        stroke="#0f4d90"
        stroke-width="3"
      />
      <text
        :x="estLabelX"
        :y="inside ? BAND_Y + BAND_H + 27 : BAND_Y - 16"
        :text-anchor="estAnchor"
        :font-size="narrow ? 13 : 14"
        font-weight="700"
        fill="#0f4d90"
        style="font-variant-numeric: tabular-nums"
      >
        {{ estLabel }}
      </text>

      <!-- range end labels (into the caption on phones) + caption -->
      <template v-if="!narrow">
        <text :x="x(props.low)" :y="BAND_Y + BAND_H + 22" text-anchor="middle" font-size="13" fill="#5d6b7c" style="font-variant-numeric: tabular-nums">
          {{ moneyCompact(props.low) }}
        </text>
        <text :x="x(props.high)" :y="BAND_Y + BAND_H + 22" text-anchor="middle" font-size="13" fill="#5d6b7c" style="font-variant-numeric: tabular-nums">
          {{ moneyCompact(props.high) }}
        </text>
      </template>
      <text :x="width / 2" :y="height - 4" text-anchor="middle" :font-size="narrow ? 12 : 11.5" :fill="narrow ? '#5d6b7c' : '#8593a4'" style="font-variant-numeric: tabular-nums">
        {{ caption }}
      </text>
    </svg>

    <details class="mt-1">
      <summary class="cursor-pointer text-body-sm font-medium text-brand-600">
        See these numbers as a table
      </summary>
      <table class="mt-2 w-full max-w-md text-left text-body-sm">
        <caption class="sr-only">Assessment versus model estimate</caption>
        <tbody>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">City’s value</th>
            <td class="py-1.5 font-semibold">{{ money(props.opa) }}</td>
          </tr>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">Our best estimate</th>
            <td class="py-1.5 font-semibold">{{ money(props.median) }}</td>
          </tr>
          <tr>
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">
              Range we’re 90% sure about
            </th>
            <td class="py-1.5">{{ money(props.low) }} to {{ money(props.high) }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>
</template>

<style scoped>
.band {
  transform-origin: center;
  animation: grow var(--duration-chart, 0.5s) var(--ease-out-civic, ease-out);
}
@keyframes grow {
  from {
    transform: scaleX(0.2);
    opacity: 0.3;
  }
  to {
    transform: scaleX(1);
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .band {
    animation: none;
  }
}
</style>
