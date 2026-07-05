<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
    <h2 class="text-lg font-bold text-slate-900">{{ title }}</h2>
    <p v-if="subtitle" class="mt-1 text-sm text-slate-600">{{ subtitle }}</p>
    <div class="mt-4">
      <slot />
    </div>
  </section>
</template>
