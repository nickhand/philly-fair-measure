<script setup lang="ts">
/** PropertySheet — the map's bottom sheet, verdict-at-a-glance + on-ramp to
 * the full report. Prop contract inferred (core: PropertyCore, close event) —
 * if your existing component's props differ, port the template only. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { scaleLinear } from 'd3-scale'
import type { PropertyCore } from '@/api/types'
import { money, moneyCompact } from '@/utils/format'
import { verdictFor } from '@/utils/verdict'

const props = defineProps<{ core: PropertyCore }>()
defineEmits<{ close: [] }>()

const verdict = computed(() => verdictFor(props.core.flag))
const hasInterval = computed(
  () =>
    props.core.model_pi_low_90 != null &&
    props.core.model_pi_high_90 != null &&
    props.core.model_median != null &&
    props.core.opa_market_value != null,
)

/** Compact 64px strip. */
const W = 343
const PAD = 18
const x = computed(() => {
  const c = props.core
  const lo = Math.min(c.model_pi_low_90!, c.opa_market_value!) * 0.94
  const hi = Math.max(c.model_pi_high_90!, c.opa_market_value!) * 1.06
  return scaleLinear().domain([lo, hi]).range([PAD, W - PAD])
})
const ariaLabel = computed(() => {
  const c = props.core
  return (
    `Estimate range ${money(c.model_pi_low_90)} to ${money(c.model_pi_high_90)}, ` +
    `best estimate ${money(c.model_median)}. City value ${money(c.opa_market_value)} is ` +
    `${c.flag === 'within_range' ? 'inside' : 'outside'} the range.`
  )
})
</script>

<template>
  <div class="rounded-t-2xl bg-white shadow-sheet" role="dialog" :aria-label="core.address">
    <div class="flex justify-center pb-0.5 pt-2" aria-hidden="true">
      <span class="h-1 w-[38px] rounded-sm bg-[#d4dbe3]"></span>
    </div>
    <div class="px-4 pb-4 pt-2">
      <div class="flex items-start justify-between gap-2.5">
        <div>
          <h2 class="text-[17px] font-extrabold text-ink">{{ core.address }}</h2>
          <p class="mt-0.5 text-[11.5px] text-muted">OPA #{{ core.parcel_id }}</p>
        </div>
        <button
          type="button"
          class="-mr-1 -mt-1 flex h-11 w-11 items-center justify-center rounded-md text-faint hover:bg-paper"
          aria-label="Close"
          @click="$emit('close')"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </button>
      </div>

      <p class="mt-1.5 inline-block rounded-full px-2.5 py-1 text-[12.5px] font-bold" :class="verdict.badgeClass">
        {{ verdict.headline }}
      </p>

      <svg
        v-if="hasInterval"
        :width="W"
        height="64"
        :viewBox="`0 0 ${W} 64`"
        role="img"
        :aria-label="ariaLabel"
        class="mt-2.5 block w-full max-w-full font-sans"
      >
        <line :x1="PAD" y1="34" :x2="W - PAD" y2="34" stroke="#dfe5ec" stroke-width="1" />
        <rect
          :x="x(core.model_pi_low_90!)"
          y="26"
          :width="Math.max(0, x(core.model_pi_high_90!) - x(core.model_pi_low_90!))"
          height="16"
          rx="4"
          fill="#dbe7f5"
          stroke="#b9d2ee"
        />
        <line :x1="x(core.model_median!)" :x2="x(core.model_median!)" y1="20" y2="48" stroke="#0f4d90" stroke-width="2.5" />
        <circle :cx="x(core.opa_market_value!)" cy="34" r="5" :fill="verdict.hex" />
        <text :x="x(core.model_pi_low_90!)" y="60" text-anchor="middle" font-size="10.5" fill="#8593a4" style="font-variant-numeric: tabular-nums">{{ moneyCompact(core.model_pi_low_90!) }}</text>
        <text :x="x(core.model_median!)" y="14" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0f4d90" style="font-variant-numeric: tabular-nums">{{ moneyCompact(core.model_median!) }}</text>
        <text :x="x(core.model_pi_high_90!)" y="60" text-anchor="middle" font-size="10.5" fill="#8593a4" style="font-variant-numeric: tabular-nums">{{ moneyCompact(core.model_pi_high_90!) }}</text>
        <text
          :x="x(core.opa_market_value!)"
          y="14"
          :text-anchor="x(core.opa_market_value!) > W - 80 ? 'end' : 'middle'"
          font-size="10.5"
          font-weight="700"
          :fill="verdict.hex"
          style="font-variant-numeric: tabular-nums"
        >
          City {{ moneyCompact(core.opa_market_value!) }}
        </text>
      </svg>

      <RouterLink
        :to="`/property/${core.parcel_id}`"
        class="mt-3 flex h-[46px] items-center justify-center gap-2 rounded-[9px] bg-brand-600 text-[14.5px] font-bold text-white hover:bg-brand-700"
      >
        See the full report
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="12" x2="19" y2="12" /><path d="M13 6l6 6-6 6" /></svg>
      </RouterLink>
    </div>
  </div>
</template>
