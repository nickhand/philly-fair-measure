<script setup lang="ts">
/** "What goes into our estimate" — signed dollar effects as diverging bars
 * around a hairline center axis. Azure = pushes the estimate up; muted
 * blue-gray = pushes it down (verdict colors stay reserved for the city's
 * number). The ± prefix carries the sign for colorblind users. */
import { computed } from 'vue'
import { moneySigned } from '@/utils/format'
import type { DriverOut } from '@/api/types'

const props = defineProps<{ drivers: DriverOut[] }>()

const maxAbs = computed(() =>
  Math.max(1, ...props.drivers.map((d) => Math.abs(d.dollars))),
)

function widthPct(d: DriverOut): number {
  return (Math.abs(d.dollars) / maxAbs.value) * 48
}
</script>

<template>
  <ul class="space-y-3" aria-label="What pushes this estimate up or down">
    <li v-for="d in props.drivers" :key="d.label + d.dollars" class="text-body-sm">
      <div class="mb-1 flex items-baseline justify-between gap-3">
        <span class="font-medium text-body">
          {{ d.label }}<span v-if="d.value" class="text-muted"> ({{ d.value }})</span>
        </span>
        <span
          class="money shrink-0 font-bold"
          :class="d.dollars >= 0 ? 'text-ink' : 'text-muted'"
        >
          {{ moneySigned(d.dollars) }}
        </span>
      </div>
      <div class="relative h-3 rounded bg-[#eef1f5]" aria-hidden="true">
        <div class="absolute inset-y-0 left-1/2 w-px bg-[#c6d0dc]"></div>
        <div
          class="absolute inset-y-0 rounded"
          :class="d.dollars >= 0 ? 'bg-brand-600' : 'bg-brand-300'"
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
