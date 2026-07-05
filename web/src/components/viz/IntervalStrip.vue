<script setup lang="ts">
/** The core explanatory graphic: our estimate range (90% band), our best
 * estimate, and the city's value positioned on the same dollar line.
 *
 * Accessibility: role=img with a full-sentence label, plus a data table
 * fallback in a <details>. Colors are never the only channel — markers are
 * labeled and shaped differently. */
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

const HEIGHT = 132
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
      <!-- city value marker (above the band so it reads first) -->
      <g :transform="`translate(${opaX}, 0)`">
        <text
          :text-anchor="opaLabelAnchor"
          y="16"
          class="fill-current text-[13px] font-semibold"
          :style="{ color: verdict.hex }"
        >
          City value {{ moneyCompact(props.opa) }}
        </text>
        <path
          d="M 0 24 L 7 34 L -7 34 Z"
          :fill="verdict.hex"
        />
        <line
          x1="0"
          x2="0"
          y1="34"
          :y2="BAND_Y + BAND_H + 6"
          :stroke="verdict.hex"
          stroke-width="2"
          stroke-dasharray="3 3"
        />
      </g>

      <!-- the 90% band -->
      <rect
        class="band"
        :x="x(props.low)"
        :y="BAND_Y"
        :width="Math.max(0, x(props.high) - x(props.low))"
        :height="BAND_H"
        rx="6"
        fill="#bfd3ee"
      />
      <!-- best estimate tick -->
      <line
        :x1="x(props.median)"
        :x2="x(props.median)"
        :y1="BAND_Y - 8"
        :y2="BAND_Y + BAND_H + 8"
        stroke="#163e75"
        stroke-width="3"
      />

      <!-- labels under the band -->
      <text :x="x(props.low)" :y="BAND_Y + BAND_H + 24" text-anchor="middle" class="fill-slate-500 text-[12px]">
        {{ moneyCompact(props.low) }}
      </text>
      <text
        :x="x(props.median)"
        :y="BAND_Y - 14"
        text-anchor="middle"
        class="fill-brand-700 text-[13px] font-semibold"
      >
        Our estimate {{ moneyCompact(props.median) }}
      </text>
      <text :x="x(props.high)" :y="BAND_Y + BAND_H + 24" text-anchor="middle" class="fill-slate-500 text-[12px]">
        {{ moneyCompact(props.high) }}
      </text>
    </svg>

    <details class="mt-1">
      <summary class="cursor-pointer text-sm font-medium text-brand-600">
        See these numbers as a table
      </summary>
      <table class="mt-2 w-full max-w-md text-left text-sm">
        <caption class="sr-only">Assessment versus model estimate</caption>
        <tbody>
          <tr class="border-b border-slate-100">
            <th scope="row" class="py-1.5 pr-4 font-medium text-slate-600">City’s value</th>
            <td class="py-1.5 font-semibold">{{ money(props.opa) }}</td>
          </tr>
          <tr class="border-b border-slate-100">
            <th scope="row" class="py-1.5 pr-4 font-medium text-slate-600">Our best estimate</th>
            <td class="py-1.5 font-semibold">{{ money(props.median) }}</td>
          </tr>
          <tr>
            <th scope="row" class="py-1.5 pr-4 font-medium text-slate-600">
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
  animation: grow 0.5s ease-out;
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
