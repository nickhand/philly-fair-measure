<script setup lang="ts">
/** Site-wide timing notice: the assessments shown are the newly released
 * Tax Year 2027 values, and the free review/appeal windows are open NOW.
 * Dismissible, persisted per browser. */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { SITE } from '@/config/site'

const route = useRoute()
/** On a property report the route param IS the OPA account number, so carry it
 * into the appeal guide and pre-fill its city deep-links; elsewhere the guide
 * asks the visitor for it. */
const appealTo = computed(() =>
  route.name === 'property' && typeof route.params.parcelId === 'string'
    ? { name: 'appeal', query: { acct: route.params.parcelId } }
    : { name: 'appeal' },
)

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
        If yours looks wrong, free First Level Reviews are due by
        {{ SITE.flrDeadlineText }}, and formal appeals by {{ SITE.appealDeadlineText }}.
        <RouterLink
          :to="appealTo"
          class="whitespace-nowrap font-bold text-brand-600 underline underline-offset-2 hover:text-brand-900"
          >How to appeal →</RouterLink
        >
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
