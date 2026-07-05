<script setup lang="ts">
/** "What goes into our estimate" — signed dollar effects as centered bars.
 * Div-based (not SVG) so it reflows naturally and reads as a list. Blue =
 * pushes the estimate up, orange = pushes it down; sign labels carry the
 * meaning for colorblind users. */
import { computed } from 'vue'
import { moneySigned } from '@/utils/format'
import type { DriverOut } from '@/api/types'

const props = defineProps<{ drivers: DriverOut[] }>()

const maxAbs = computed(() =>
  Math.max(1, ...props.drivers.map((d) => Math.abs(d.dollars))),
)

function widthPct(d: DriverOut): number {
  return (Math.abs(d.dollars) / maxAbs.value) * 50
}
</script>

<template>
  <ul class="space-y-3" aria-label="What pushes this estimate up or down">
    <li v-for="d in props.drivers" :key="d.label + d.dollars" class="text-sm">
      <div class="mb-1 flex items-baseline justify-between gap-3">
        <span class="font-medium text-slate-800">
          {{ d.label }}<span v-if="d.value" class="text-slate-500"> ({{ d.value }})</span>
        </span>
        <span
          class="shrink-0 font-semibold tabular-nums"
          :class="d.dollars >= 0 ? 'text-under' : 'text-over'"
        >
          {{ moneySigned(d.dollars) }}
        </span>
      </div>
      <div class="relative h-3 rounded bg-slate-100" aria-hidden="true">
        <div class="absolute inset-y-0 left-1/2 w-px bg-slate-300"></div>
        <div
          class="absolute inset-y-0 rounded"
          :class="d.dollars >= 0 ? 'bg-under' : 'bg-over'"
          :style="
            d.dollars >= 0
              ? { left: '50%', width: `${widthPct(d)}%` }
              : { right: '50%', width: `${widthPct(d)}%` }
          "
        ></div>
      </div>
    </li>
  </ul>
</template>
