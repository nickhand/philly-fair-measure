<script setup lang="ts">
/** Standalone appeal guide: the free step-by-step, reachable from the banner
 * and the top nav without first looking up a home. Two steps deep-link by OPA
 * account number, so we take it as a `?acct=` query (the banner passes it
 * automatically from a report) or let the visitor type it in. */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { SITE } from '@/config/site'
import type { SearchHit } from '@/api/types'
import AddressSearch from '@/components/search/AddressSearch.vue'
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

/** Picking an address fills in its OPA account number (the parcel id), so the
 * city deep-links below point at the visitor's home without leaving the page. */
function onSelectAddress(hit: SearchHit) {
  acct.value = hit.parcel_id
}

/** Clearing the address field (its X) also clears the account it filled in. */
function onClearAddress() {
  acct.value = ''
}

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
      If the city’s Tax Year {{ SITE.assessmentTaxYear }} value looks too high, you can challenge it
      for free, in two stages. First, a First Level Review with the <strong>OPA</strong> (the Office
      of Property Assessment), due by <strong>{{ SITE.flrDeadlineText }}</strong>. Still disagree
      after that? A formal appeal to the <strong>BRT</strong> (the Board of Revision of Taxes), due by
      <strong>{{ SITE.appealDeadlineText }}</strong>.
    </p>

    <!-- point the guide at a home: address search fills the OPA account number,
         which the two city links inside the steps need -->
    <div class="mt-5 rounded-xl border border-line-soft bg-white p-4 sm:p-5">
      <p class="text-body-sm font-bold text-ink">Point the steps at your home</p>
      <p class="mt-1 text-caption text-faint">
        Search your address and we’ll pull your OPA account number, so the city links below open your
        own property.
      </p>
      <div class="mt-2.5">
        <AddressSearch hide-check @select="onSelectAddress" @clear="onClearAddress" />
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <label for="acct" class="shrink-0 text-caption font-semibold text-muted"
          >OPA account number</label
        >
        <input
          id="acct"
          v-model="acct"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          placeholder="9 digits"
          class="min-h-9 w-40 rounded-md border border-line bg-white px-2.5 text-body-sm font-semibold tabular-nums text-ink focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200"
        />
        <span v-if="parcelId" class="text-caption font-semibold text-brand-600"
          >✓ set for #{{ parcelId }}</span
        >
      </div>
      <p class="mt-1.5 text-caption text-muted">
        Filled in when you pick an address, or type the 9-digit number from your assessment notice.
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
