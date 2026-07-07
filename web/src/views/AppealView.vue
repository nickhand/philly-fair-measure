<script setup lang="ts">
/** Standalone appeal guide: the free step-by-step, reachable from the banner
 * and the top nav without first looking up a home. Two steps deep-link by OPA
 * account number, so we take it as a `?acct=` query (the banner passes it
 * automatically from a report) or let the visitor type it in. */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { SITE } from '@/config/site'
import AppealSteps from '@/components/ui/AppealSteps.vue'

const route = useRoute()
const acct = ref(typeof route.query.acct === 'string' ? route.query.acct : '')

/** Pick up ?acct= when it arrives without a remount (e.g. the visitor is already
 * on this page and follows the banner link from a report). Typing is untouched:
 * editing the field never changes the query, so it won't re-trigger this. */
watch(
  () => route.query.acct,
  (v) => {
    if (typeof v === 'string' && v) acct.value = v
  },
)

/** OPA account numbers are 9 digits; strip any formatting the visitor pastes.
 * Only feed the links a plausible one so we never build a broken deep-link. */
const parcelId = computed(() => {
  const digits = acct.value.replace(/\D/g, '')
  return digits.length >= 9 ? digits : null
})
</script>

<template>
  <div class="mx-auto max-w-2xl px-4 py-6 sm:py-8">
    <p class="text-caption font-bold uppercase tracking-[0.1em] text-brand-600">Take action</p>
    <h1 class="mt-2 font-display text-[28px] font-bold leading-tight text-ink sm:text-[34px]">
      Appeal your assessment
    </h1>
    <p class="mt-2.5 text-base leading-relaxed text-body">
      If the city’s value looks too high, you can challenge it, and it costs nothing. For Tax Year
      {{ SITE.assessmentTaxYear }}, free First Level Reviews are due by
      <strong>{{ SITE.flrDeadlineText }}</strong>, and formal appeals by
      <strong>{{ SITE.appealDeadlineText }}</strong>.
    </p>

    <!-- account number: the two city links below need it -->
    <div class="mt-5 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <label for="acct" class="text-body-sm font-bold text-ink">Your OPA account number</label>
      <p class="mt-1 text-caption text-faint">
        The 9-digit number on your assessment notice, or search your address at
        <a href="https://property.phila.gov" rel="noopener" class="font-semibold text-brand-600 underline"
          >property.phila.gov</a
        >. Enter it to point the steps below straight at your property.
      </p>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <input
          id="acct"
          v-model="acct"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          placeholder="e.g. 883309050"
          class="min-h-11 w-full max-w-[16rem] rounded-md border border-line bg-white px-3 text-body font-semibold tabular-nums text-ink focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200"
        />
        <span v-if="parcelId" class="text-caption font-semibold text-brand-600">
          Set for account #{{ parcelId }}
        </span>
      </div>
      <p class="mt-2 text-caption text-muted">
        Don’t know it?
        <RouterLink to="/" class="font-semibold text-brand-600 underline">Look up your home</RouterLink>
        and open its report, which fills this in for you and lists your home’s specific facts.
      </p>
    </div>

    <AppealSteps :parcel-id="parcelId" class="mt-5" />

    <p class="mt-4 text-caption leading-normal text-faint">
      This is public guidance, not legal or appraisal advice. The deadlines are set by the City of
      Philadelphia and can change; confirm them on
      <a
        href="https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/"
        rel="noopener"
        class="font-semibold text-brand-600 underline"
        >phila.gov</a
      >.
    </p>
  </div>
</template>
