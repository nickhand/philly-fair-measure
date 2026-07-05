<script setup lang="ts">
/** Mobile-first bottom sheet shown when a home is tapped on the map. */
import { computed } from 'vue'
import type { PropertyCore } from '@/api/types'
import { money } from '@/utils/format'
import { verdictFor } from '@/utils/verdict'

const props = defineProps<{ property: PropertyCore }>()
defineEmits<{ close: [] }>()

const verdict = computed(() => verdictFor(props.property.flag))
</script>

<template>
  <div
    class="pointer-events-auto fixed inset-x-0 bottom-0 z-30 mx-auto max-w-xl rounded-t-2xl border border-slate-200 bg-white p-5 shadow-2xl sm:bottom-6 sm:rounded-2xl"
    role="dialog"
    aria-modal="false"
    :aria-label="`Assessment summary for ${property.address}`"
  >
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-bold text-slate-900">{{ property.address }}</h2>
        <p
          class="mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-bold"
          :class="verdict.badgeClass"
        >
          {{ verdict.headline }}
        </p>
      </div>
      <button
        type="button"
        class="min-h-11 min-w-11 rounded-lg text-2xl leading-none text-slate-500 hover:bg-slate-100"
        aria-label="Close summary"
        @click="$emit('close')"
      >
        ×
      </button>
    </div>

    <dl class="mt-3 grid grid-cols-2 gap-3 text-sm">
      <div class="rounded-lg bg-slate-50 p-3">
        <dt class="text-slate-600">City’s value</dt>
        <dd class="text-lg font-bold text-slate-900">{{ money(property.opa_market_value) }}</dd>
      </div>
      <div class="rounded-lg bg-slate-50 p-3">
        <dt class="text-slate-600">Our estimate</dt>
        <dd class="text-lg font-bold text-brand-700">{{ money(property.model_median) }}</dd>
      </div>
    </dl>

    <RouterLink
      :to="{ name: 'property', params: { parcelId: property.parcel_id } }"
      class="mt-4 block w-full rounded-xl bg-brand-600 py-3 text-center font-bold text-white hover:bg-brand-700"
    >
      See the full report
    </RouterLink>
  </div>
</template>
