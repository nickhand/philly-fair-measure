<script setup lang="ts">
/** The "honesty note" — trust furniture, always visible (never buried behind
 * a toggle). Brand-blue by default; the gold variant is reserved for the
 * twin-uniformity callout and "what we cannot see". */
import { Info } from 'lucide-vue-next'

withDefaults(defineProps<{ label?: string; variant?: 'brand' | 'gold' }>(), {
  label: undefined,
  variant: 'brand',
})
</script>

<template>
  <div
    role="note"
    class="mt-3 flex gap-2.5 rounded-md border p-3 text-body-sm"
    :class="
      variant === 'gold' ? 'border-gold-border bg-gold-soft' : 'border-[#d8e4f2] bg-[#eef4fb]'
    "
  >
    <Info
      aria-hidden="true"
      :size="16"
      class="mt-0.5 shrink-0"
      :class="variant === 'gold' ? 'text-gold-700' : 'text-brand-600'"
    />
    <div class="text-body">
      <p
        v-if="label"
        class="mb-0.5 font-bold"
        :class="variant === 'gold' ? 'text-gold-700' : 'text-brand-600'"
      >
        {{ label }}
      </p>
      <slot />
    </div>
  </div>
</template>
