<script setup lang="ts">
/** DriverBars — diverging bars around a hairline center axis.
 * Positive (pushes value up) = azure; negative = muted blue-gray.
 * Prop contract inferred from PropertyView.vue usage (`:drivers="report.drivers.drivers"`);
 * assumed shape { label: string; dollars: number }[] — verify against api/types.ts. */
import { computed } from 'vue'
import { moneyCompact } from '@/utils/format'

const props = defineProps<{ drivers: { label: string; dollars: number }[] }>()

const sorted = computed(() =>
  [...props.drivers].sort((a, b) => Math.abs(b.dollars) - Math.abs(a.dollars)),
)
const max = computed(() => Math.max(1, ...props.drivers.map((d) => Math.abs(d.dollars))))
/** Widest bar spans 48% of the track (half-track minus breathing room). */
const widthPct = (d: { dollars: number }) => (Math.abs(d.dollars) / max.value) * 48

const ariaLabel = computed(() => {
  const top = sorted.value[0]
  if (!top) return 'No value drivers available.'
  return (
    `The largest adjustments to this home's estimate: ` +
    sorted.value
      .map((d) => `${d.label}, ${d.dollars >= 0 ? 'adds' : 'subtracts'} ${moneyCompact(Math.abs(d.dollars))}`)
      .join('; ') +
    '.'
  )
})
</script>

<template>
  <div>
    <div role="img" :aria-label="ariaLabel" class="flex flex-col gap-2.5">
      <div
        v-for="d in sorted"
        :key="d.label"
        aria-hidden="true"
        class="grid grid-cols-[104px_1fr_52px] items-center gap-2 sm:grid-cols-[128px_1fr_52px] sm:gap-2.5"
      >
        <span class="text-xs leading-tight text-body">{{ d.label }}</span>
        <div class="relative h-2.5 rounded-[5px] bg-[#eef1f5]">
          <div class="absolute left-1/2 -top-[3px] -bottom-[3px] w-px bg-[#c6d0dc]"></div>
          <div
            v-if="d.dollars >= 0"
            class="absolute left-1/2 h-full rounded-r-[5px] bg-brand-600"
            :style="{ width: widthPct(d) + '%' }"
          ></div>
          <div
            v-else
            class="absolute right-1/2 h-full rounded-l-[5px] bg-brand-300"
            :style="{ width: widthPct(d) + '%' }"
          ></div>
        </div>
        <span
          class="text-right text-xs font-bold tabular-nums"
          :class="d.dollars >= 0 ? 'text-ink' : 'text-muted'"
        >
          {{ d.dollars >= 0 ? '+' : '−' }}{{ moneyCompact(Math.abs(d.dollars)) }}
        </span>
      </div>
    </div>

    <details class="mt-2">
      <summary class="cursor-pointer text-sm font-medium text-brand-600">See these numbers as a table</summary>
      <table class="mt-2 w-full max-w-md text-left text-sm">
        <caption class="sr-only">Largest adjustments to the estimate</caption>
        <tbody>
          <tr v-for="d in sorted" :key="d.label" class="border-b border-line-faint">
            <th scope="row" class="py-1.5 pr-4 font-medium text-muted">{{ d.label }}</th>
            <td class="py-1.5 font-semibold tabular-nums">
              {{ d.dollars >= 0 ? '+' : '−' }}{{ moneyCompact(Math.abs(d.dollars)) }}
            </td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>
</template>
