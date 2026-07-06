<script setup lang="ts">
/** PropertySheet — the map's bottom sheet, verdict-at-a-glance + on-ramp to
 * the full report. Handoff SFC with the prop kept as `property` (existing
 * API). Content-only: MapView owns the positioning wrapper. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { scaleLinear } from 'd3-scale'
import type { PropertyCore } from '@/api/types'
import { money, moneyCompact } from '@/utils/format'
import { verdictFor } from '@/utils/verdict'

const props = defineProps<{ property: PropertyCore }>()
defineEmits<{ close: [] }>()

const verdict = computed(() => verdictFor(props.property.flag, props.property.attention))
const hasInterval = computed(
  () =>
    props.property.model_pi_low_90 != null &&
    props.property.model_pi_high_90 != null &&
    props.property.model_median != null &&
    props.property.opa_market_value != null,
)

/** The band the sheet shows: where both uncertainty methods agree
 * (display_pi_*), falling back to the flag-anchoring model band on older
 * payloads. */
const bandLo = computed(() => props.property.display_pi_low_90 ?? props.property.model_pi_low_90)
const bandHi = computed(() => props.property.display_pi_high_90 ?? props.property.model_pi_high_90)

/** Compact 64px strip. */
const W = 343
const PAD = 18
const x = computed(() => {
  const c = props.property
  const lo = Math.min(bandLo.value!, c.opa_market_value!) * 0.94
  const hi = Math.max(bandHi.value!, c.opa_market_value!) * 1.06
  return scaleLinear().domain([lo, hi]).range([PAD, W - PAD])
})
const ariaLabel = computed(() => {
  const c = props.property
  return (
    `Estimate range ${money(bandLo.value)} to ${money(bandHi.value)}, ` +
    `best estimate ${money(c.model_median)}. City value ${money(c.opa_market_value)} is ` +
    `${c.flag === 'within_range' ? 'inside' : 'outside'} the range.`
  )
})

/** Top-row labels ("City" and the estimate) collide when the two values are
 * close: stagger the city label onto a second row. Both also clamp at the
 * strip's edges so text never cuts off. */
const opaSx = computed(() => x.value(props.property.opa_market_value!))
const medSx = computed(() => x.value(props.property.model_median!))
const labelsClose = computed(() => Math.abs(opaSx.value - medSx.value) < 92)
const cityLabelY = computed(() => (labelsClose.value ? 26 : 14))
function clampX(v: number): number {
  return Math.max(PAD + 2, Math.min(W - PAD - 2, v))
}
function edgeAnchor(v: number): 'start' | 'middle' | 'end' {
  if (v < PAD + 42) return 'start'
  if (v > W - PAD - 42) return 'end'
  return 'middle'
}
</script>

<template>
  <div class="rounded-t-2xl bg-white shadow-sheet" role="dialog" :aria-label="property.address">
    <div class="flex justify-center pb-0.5 pt-2" aria-hidden="true">
      <span class="h-1 w-[38px] rounded-sm bg-[#d4dbe3]"></span>
    </div>
    <div class="px-4 pb-4 pt-2">
      <div class="flex items-start justify-between gap-2.5">
        <div>
          <h2 class="text-title font-extrabold text-ink">{{ property.address }}</h2>
          <p class="mt-0.5 text-caption text-muted">OPA #{{ property.parcel_id }}</p>
        </div>
        <button
          type="button"
          class="-mr-1 -mt-1 flex h-11 w-11 items-center justify-center rounded-md text-faint hover:bg-paper"
          aria-label="Close"
          @click="$emit('close')"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </button>
      </div>

      <p class="mt-1.5 inline-block rounded-full px-2.5 py-1 text-caption font-bold" :class="verdict.badgeClass">
        {{ verdict.headline }}
      </p>

      <svg
        v-if="hasInterval"
        :width="W"
        height="76"
        :viewBox="`0 0 ${W} 76`"
        role="img"
        :aria-label="ariaLabel"
        class="mt-2.5 block w-full max-w-full font-sans"
      >
        <line :x1="PAD" y1="46" :x2="W - PAD" y2="46" stroke="#dfe5ec" stroke-width="1" />
        <rect
          :x="x(bandLo!)"
          y="38"
          :width="Math.max(0, x(bandHi!) - x(bandLo!))"
          height="16"
          rx="4"
          fill="#dbe7f5"
          stroke="#b9d2ee"
        />
        <line :x1="medSx" :x2="medSx" y1="32" y2="60" stroke="#0f4d90" stroke-width="2.5" />
        <circle :cx="opaSx" cy="46" r="5" :fill="verdict.hex" />
        <text :x="clampX(x(bandLo!))" y="72" text-anchor="middle" font-size="11.5" fill="#8593a4" style="font-variant-numeric: tabular-nums">{{ moneyCompact(bandLo!) }}</text>
        <text :x="clampX(medSx)" y="14" :text-anchor="edgeAnchor(medSx)" font-size="11.5" font-weight="700" fill="#0f4d90" style="font-variant-numeric: tabular-nums">Ours {{ moneyCompact(property.model_median!) }}</text>
        <text :x="clampX(x(bandHi!))" y="72" text-anchor="middle" font-size="11.5" fill="#8593a4" style="font-variant-numeric: tabular-nums">{{ moneyCompact(bandHi!) }}</text>
        <text
          :x="clampX(opaSx)"
          :y="cityLabelY"
          :text-anchor="edgeAnchor(opaSx)"
          font-size="11.5"
          font-weight="700"
          :fill="verdict.hex"
          style="font-variant-numeric: tabular-nums"
        >
          City {{ moneyCompact(property.opa_market_value!) }}
        </text>
      </svg>

      <dl v-else class="mt-3 grid grid-cols-2 gap-3 text-body-sm">
        <div class="rounded-md bg-paper p-3">
          <dt class="text-muted">City’s value</dt>
          <dd class="text-lg font-bold tabular-nums text-ink">{{ money(property.opa_market_value) }}</dd>
        </div>
        <div class="rounded-md bg-paper p-3">
          <dt class="text-muted">Our estimate</dt>
          <dd class="text-lg font-bold tabular-nums text-brand-600">{{ money(property.model_median) }}</dd>
        </div>
      </dl>

      <RouterLink
        :to="`/property/${property.parcel_id}`"
        class="mt-3 flex h-[46px] items-center justify-center gap-2 rounded-[9px] bg-brand-600 text-base font-bold text-white hover:bg-brand-700"
      >
        See the full report
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="12" x2="19" y2="12" /><path d="M13 6l6 6-6 6" /></svg>
      </RouterLink>
    </div>
  </div>
</template>
