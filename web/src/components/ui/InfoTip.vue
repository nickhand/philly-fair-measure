<script setup lang="ts">
/** InfoTip — the "honesty note", a first-class trust element.
 * variant "azure" (default): model explanations. variant "gold": reserved for
 * the twin-uniformity callout and "what we cannot see" honesty blocks.
 * Prop contract inferred from PropertyView.vue usage (optional label + slot). */
withDefaults(defineProps<{ label?: string; variant?: 'azure' | 'gold' }>(), {
  variant: 'azure',
})
</script>

<template>
  <div
    class="mt-3 flex gap-2.5 rounded-md border p-3"
    :class="variant === 'gold' ? 'border-gold-border bg-gold-soft' : 'border-[#d8e4f2] bg-[#eef4fb]'"
  >
    <svg
      width="18" height="18" viewBox="0 0 24 24" fill="none"
      :stroke="variant === 'gold' ? '#8a6100' : '#0f4d90'"
      stroke-width="2" stroke-linecap="round" aria-hidden="true"
      class="mt-0.5 shrink-0"
    >
      <circle cx="12" cy="12" r="9.5" />
      <line x1="12" y1="11" x2="12" y2="16.5" />
      <circle cx="12" cy="7.5" r="0.6" :fill="variant === 'gold' ? '#8a6100' : '#0f4d90'" />
    </svg>
    <div class="text-caption leading-relaxed text-body">
      <p v-if="label" class="font-bold" :class="variant === 'gold' ? 'text-gold-700' : 'text-brand-600'">
        {{ label }}
      </p>
      <p :class="label ? 'mt-1' : ''"><slot /></p>
    </div>
  </div>
</template>
