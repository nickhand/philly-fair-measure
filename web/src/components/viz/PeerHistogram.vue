<script setup lang="ts">
/** Where this home sits among its neighbors: the distribution of
 * (city value ÷ our estimate) for similar homes nearby. Your bin is
 * highlighted; the peer median is a solid azure line; "you" is a dashed
 * line + dot in the verdict color (color is never the only channel —
 * both markers carry direct labels). */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { scaleLinear } from 'd3-scale'
import { pct } from '@/utils/format'
import type { HistBin } from '@/api/types'

const props = withDefaults(
  defineProps<{
    histogram: HistBin[]
    you: number
    peerMedian: number
    /** Verdict hex for the "you" marker; defaults to ink. */
    youHex?: string
  }>(),
  { youHex: '#16243a' },
)

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

const HEIGHT = 200
const PAD = { left: 10, right: 10, top: 36, bottom: 44 }

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

function isYourBin(b: HistBin): boolean {
  return clampedYou.value >= b.x0 && clampedYou.value < b.x1
}

const medianAnchor = computed(() =>
  x.value(props.peerMedian) <= x.value(clampedYou.value) ? 'end' : 'start',
)

const ticks = computed(() =>
  [0.7, 1.0, 1.3].filter((t) => t >= domain.value[0] && t <= domain.value[1]),
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
      <!-- bins (yours highlighted) -->
      <rect
        v-for="b in props.histogram"
        :key="b.x0"
        :x="x(b.x0) + 1"
        :y="y(b.n)"
        :width="Math.max(0, x(b.x1) - x(b.x0) - 2)"
        :height="Math.max(0, HEIGHT - PAD.bottom - y(b.n))"
        rx="1.5"
        :fill="isYourBin(b) ? '#ffd9bd' : '#c9d9ec'"
      />

      <!-- quiet baseline -->
      <line
        :x1="PAD.left"
        :x2="width - PAD.right"
        :y1="HEIGHT - PAD.bottom"
        :y2="HEIGHT - PAD.bottom"
        stroke="#dfe5ec"
        stroke-width="1"
      />

      <!-- peer median: solid azure -->
      <g>
        <line
          :x1="x(props.peerMedian)"
          :x2="x(props.peerMedian)"
          :y1="PAD.top - 6"
          :y2="HEIGHT - PAD.bottom"
          stroke="#0f4d90"
          stroke-width="2"
        />
        <text
          :x="x(props.peerMedian) + (medianAnchor === 'start' ? 6 : -6)"
          :y="PAD.top + 6"
          :text-anchor="medianAnchor"
          fill="#0f4d90"
          class="text-[12px] font-bold"
        >
          Similar homes’ middle {{ pct(props.peerMedian) }}
        </text>
      </g>

      <!-- you: dashed verdict-colored line + dot -->
      <g :transform="`translate(${x(clampedYou)}, 0)`">
        <line
          x1="0"
          x2="0"
          y1="18"
          :y2="HEIGHT - PAD.bottom"
          :stroke="props.youHex"
          stroke-width="2"
          stroke-dasharray="4 3"
        />
        <circle cx="0" cy="14" r="4" :fill="props.youHex" />
        <text
          x="0"
          y="9"
          text-anchor="middle"
          :fill="props.youHex"
          class="text-[13px] font-bold"
        >
          You {{ pct(props.you) }}
        </text>
      </g>

      <!-- axis ticks + caption -->
      <text
        v-for="t in ticks"
        :key="t"
        :x="x(t)"
        :y="HEIGHT - 26"
        text-anchor="middle"
        fill="#5d6b7c"
        class="text-[12px]"
      >
        {{ Math.round(t * 100) }}%
      </text>
      <text
        :x="(PAD.left + width - PAD.right) / 2"
        :y="HEIGHT - 8"
        text-anchor="middle"
        fill="#8593a4"
        class="text-[10.5px]"
      >
        assessment as % of our estimate
      </text>
    </svg>
  </div>
</template>
