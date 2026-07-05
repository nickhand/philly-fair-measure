<script setup lang="ts">
/** Tap-to-expand plain-language definition. Native <details> = accessible
 * for free (keyboard, screen readers, no JS). */
defineProps<{ label?: string }>()
</script>

<template>
  <details class="group mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm">
    <summary
      class="cursor-pointer list-none font-medium text-brand-600 group-open:mb-1.5"
    >
      <span aria-hidden="true">ⓘ</span> {{ label ?? 'What does this mean?' }}
    </summary>
    <div class="text-slate-700">
      <slot />
    </div>
  </details>
</template>
