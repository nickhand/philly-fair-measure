<script setup lang="ts">
/** Site-wide timing notice: the assessments shown are the newly released
 * Tax Year 2027 values, and the free review/appeal windows are open NOW.
 * Dismissible, persisted per browser. */
import { onMounted, ref } from 'vue'
import { SITE } from '@/config/site'

const KEY = `fm-ty${SITE.assessmentTaxYear}-banner-dismissed`
const show = ref(false)

onMounted(() => {
  show.value = localStorage.getItem(KEY) !== '1'
})

function dismiss() {
  localStorage.setItem(KEY, '1')
  show.value = false
}
</script>

<template>
  <div
    v-if="show"
    role="region"
    aria-label="Assessment timing notice"
    class="border-b border-gold-tint-border bg-gold-tint"
  >
    <div class="mx-auto flex max-w-5xl items-start justify-between gap-3 px-4 py-2.5">
      <p class="text-body-sm leading-relaxed text-body">
        <strong class="text-ink">The new Tax Year {{ SITE.assessmentTaxYear }} assessments are
        out.</strong>
        If yours looks wrong, the free review and appeal windows are open now — formal appeals are
        due by {{ SITE.appealDeadlineText }}.
        <RouterLink to="/" class="font-semibold text-brand-600 underline">Check your home</RouterLink>.
      </p>
      <button
        type="button"
        class="flex min-h-9 min-w-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-gold-soft"
        aria-label="Dismiss this notice"
        @click="dismiss"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
      </button>
    </div>
  </div>
</template>
