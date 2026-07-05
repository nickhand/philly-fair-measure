<script setup lang="ts">
/** Mobile-first bottom sheet shown when a home is tapped on the map. */
import { computed } from 'vue'
import { X } from 'lucide-vue-next'
import type { PropertyCore } from '@/api/types'
import { money, moneyCompact } from '@/utils/format'
import { verdictFor } from '@/utils/verdict'

const props = defineProps<{ property: PropertyCore }>()
defineEmits<{ close: [] }>()

const verdict = computed(() => verdictFor(props.property.flag))

/** Compact strip geometry (viewBox 0 0 320 64). */
const strip = computed(() => {
  const p = props.property
  if (p.model_pi_low_90 == null || p.model_pi_high_90 == null || p.model_median == null ||
      p.opa_market_value == null) {
    return null
  }
  const lo = Math.min(p.model_pi_low_90, p.opa_market_value) * 0.94
  const hi = Math.max(p.model_pi_high_90, p.opa_market_value) * 1.06
  const sx = (v: number) => 10 + ((v - lo) / (hi - lo)) * 300
  return {
    bandX: sx(p.model_pi_low_90),
    bandW: sx(p.model_pi_high_90) - sx(p.model_pi_low_90),
    tickX: sx(p.model_median),
    opaX: sx(p.opa_market_value),
  }
})
</script>

<template>
  <div
    class="pointer-events-auto fixed inset-x-0 bottom-0 z-30 mx-auto max-w-xl rounded-t-2xl border border-line-soft bg-white p-4 shadow-sheet sm:bottom-6 sm:rounded-2xl sm:p-5"
    role="dialog"
    aria-modal="false"
    :aria-label="`Assessment summary for ${property.address}`"
  >
    <div aria-hidden="true" class="mx-auto mb-3 h-1 w-[38px] rounded-full bg-line sm:hidden"></div>
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="text-[17px] font-extrabold text-ink">{{ property.address }}</h2>
        <p class="text-caption text-faint">OPA #{{ property.parcel_id }}</p>
        <p
          class="mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-caption font-bold"
          :class="verdict.badgeClass"
        >
          {{ verdict.headline }}
        </p>
      </div>
      <button
        type="button"
        class="flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted hover:bg-paper"
        aria-label="Close summary"
        @click="$emit('close')"
      >
        <X :size="20" aria-hidden="true" />
      </button>
    </div>

    <!-- compact interval strip -->
    <svg
      v-if="strip"
      viewBox="0 0 320 64"
      class="mt-3 block h-16 w-full"
      role="img"
      :aria-label="`City value ${money(property.opa_market_value)}, our estimate ${money(property.model_median)}.`"
    >
      <rect :x="strip.bandX" y="24" :width="Math.max(0, strip.bandW)" height="14" rx="7" fill="#dbe7f5" stroke="#b9d2ee" />
      <line :x1="strip.tickX" :x2="strip.tickX" y1="19" y2="43" stroke="#0f4d90" stroke-width="2.5" />
      <circle :cx="strip.opaX" cy="31" r="4" :fill="verdict.hex" stroke="#fff" stroke-width="1.5" />
      <text :x="strip.tickX" y="12" text-anchor="middle" fill="#0f4d90" class="text-[10px] font-bold">
        Ours {{ moneyCompact(property.model_median) }}
      </text>
      <text :x="strip.opaX" y="57" text-anchor="middle" :fill="verdict.hex" class="text-[10px] font-bold">
        City {{ moneyCompact(property.opa_market_value) }}
      </text>
      <text x="10" y="57" fill="#8593a4" class="text-[9px]">{{ moneyCompact(property.model_pi_low_90) }}</text>
      <text x="310" y="57" text-anchor="end" fill="#8593a4" class="text-[9px]">
        {{ moneyCompact(property.model_pi_high_90) }}
      </text>
    </svg>

    <dl v-else class="mt-3 grid grid-cols-2 gap-3 text-body-sm">
      <div class="rounded-md bg-paper p-3">
        <dt class="text-muted">City’s value</dt>
        <dd class="money text-lg font-bold text-ink">{{ money(property.opa_market_value) }}</dd>
      </div>
      <div class="rounded-md bg-paper p-3">
        <dt class="text-muted">Our estimate</dt>
        <dd class="money text-lg font-bold text-brand-600">{{ money(property.model_median) }}</dd>
      </div>
    </dl>

    <RouterLink
      :to="{ name: 'property', params: { parcelId: property.parcel_id } }"
      class="mt-3 flex h-[46px] w-full items-center justify-center rounded-md bg-brand-600 text-center font-bold text-white hover:bg-brand-700"
    >
      See the full report
    </RouterLink>
  </div>
</template>
