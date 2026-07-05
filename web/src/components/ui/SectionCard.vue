<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <!-- panels get border only; the verdict card alone carries a shadow -->
  <section class="rounded-lg border border-line-soft bg-white p-4 sm:p-5">
    <h2 class="text-title font-bold text-ink">{{ title }}</h2>
    <p v-if="subtitle" class="mt-1 text-[0.78rem] leading-snug text-muted">{{ subtitle }}</p>
    <div class="mt-4">
      <slot />
    </div>
  </section>
</template>
