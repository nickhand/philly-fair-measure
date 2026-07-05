<script setup lang="ts">
/** The core explanatory graphic: our estimate range (90% band), our best
 * estimate, and the city's value positioned on the same dollar line.
 *
 * Chart grammar (Flag & Ledger): azure = our model, verdict color = the
 * city's number for you. City marker reads through shape (triangle + dashed
 * drop line + dot) as well as color.
 *
 * Accessibility: role=img with a full-sentence label, plus a data table
 * fallback in a <details>. */
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
  observer = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width
    if (w) width.value = Math.max(280, w)
  })
  if (wrapper.value) observer.observe(wrapper.value)
})
onBeforeUnmount(() => observer?.disconnect())

const HEIGHT = 150
const PAD = 18
const BAND_Y = 74
const BAND_H = 26

const x = computed(() => {
  const lo = Math.min(props.low, props.opa) * 0.94
  const hi = Math.max(props.high, props.opa) * 1.06
  return scaleLinear().domain([lo, hi]).range([PAD, width.value - PAD])
})

const verdict = computed(() => verdictFor(props.flag))
const opaX = computed(() => x.value(props.opa))
const midX = computed(() => (x.value(props.low) + x.value(props.high)) / 2)
const opaLabelAnchor = computed(() => {
  const frac = (opaX.value - PAD) / Math.max(1, width.value - 2 * PAD)
  return frac < 0.15 ? 'start' : frac > 0.85 ? 'end' : 'middle'
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
      :height="HEIGHT"
      :viewBox="`0 0 ${width} ${HEIGHT}`"
      role="img"
      :aria-label="ariaLabel"
      class="block w-full"
    >
      <!-- city value marker: label, triangle-down, dashed drop line, dot -->
      <g :transform="`translate(${opaX}, 0)`">
        <text
          :text-anchor="opaLabelAnchor"
          y="16"
          class="text-[13px] font-bold"
          :fill="verdict.hex"
        >
          City value {{ moneyCompact(props.opa) }}
        </text>
        <path d="M 0 24 L 6.5 33 L -6.5 33 Z" :fill="verdict.hex" />
        <line
          x1="0"
          x2="0"
          y1="33"
          :y2="BAND_Y + BAND_H + 6"
          :stroke="verdict.hex"
          stroke-width="2"
          stroke-dasharray="3 3"
        />
        <circle cx="0" :cy="BAND_Y + BAND_H + 9" r="3.5" :fill="verdict.hex" />
      </g>

      <!-- the 90% band -->
      <rect
        class="band"
        :x="x(props.low)"
        :y="BAND_Y"
        :width="Math.max(0, x(props.high) - x(props.low))"
        :height="BAND_H"
        rx="6"
        fill="#dbe7f5"
        stroke="#b9d2ee"
      />
      <!-- best estimate tick -->
      <line
        :x1="x(props.median)"
        :x2="x(props.median)"
        :y1="BAND_Y - 8"
        :y2="BAND_Y + BAND_H + 8"
        stroke="#0f4d90"
        stroke-width="3"
      />

      <!-- labels -->
      <text
        :x="x(props.median)"
        :y="BAND_Y - 14"
        text-anchor="middle"
        fill="#0f4d90"
        class="text-[13px] font-bold"
      >
        Our estimate {{ moneyCompact(props.median) }}
      </text>
      <text
        :x="x(props.low)"
        :y="BAND_Y + BAND_H + 26"
        text-anchor="middle"
        fill="#5d6b7c"
        class="text-[12px]"
      >
        {{ moneyCompact(props.low) }}
      </text>
      <text
        :x="x(props.high)"
        :y="BAND_Y + BAND_H + 26"
        text-anchor="middle"
        fill="#5d6b7c"
        class="text-[12px]"
      >
        {{ moneyCompact(props.high) }}
      </text>
      <text
        :x="midX"
        :y="HEIGHT - 6"
        text-anchor="middle"
        fill="#8593a4"
        class="text-[10.5px]"
      >
        range we’re 90% sure about
      </text>
    </svg>

    <details class="mt-1">
      <summary class="cursor-pointer text-body-sm font-semibold text-brand-600">
        See these numbers as a table
      </summary>
      <table class="mt-2 w-full max-w-md text-left text-body-sm">
        <caption class="sr-only">Assessment versus model estimate</caption>
        <tbody>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">City’s value</th>
            <td class="py-1.5 font-bold text-ink">{{ money(props.opa) }}</td>
          </tr>
          <tr class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">Our best estimate</th>
            <td class="py-1.5 font-bold text-ink">{{ money(props.median) }}</td>
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
  animation: grow var(--duration-chart, 500ms) var(--ease-out-civic, ease-out);
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
