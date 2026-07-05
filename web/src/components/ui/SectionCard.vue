<script setup lang="ts">
/** SectionCard — supporting panel. Deliberately quieter than the verdict card:
 * border only, no shadow. Prop contract inferred from PropertyView.vue usage
 * (title, subtitle, class passthrough + default slot) — verify against yours. */
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <section class="rounded-lg border border-line-soft bg-white p-4 sm:p-5">
    <h2 class="text-base font-bold text-ink sm:text-title">{{ title }}</h2>
    <p v-if="subtitle" class="mt-0.5 text-caption leading-snug text-muted">{{ subtitle }}</p>
    <div class="mt-3">
      <slot />
    </div>
  </section>
</template>
