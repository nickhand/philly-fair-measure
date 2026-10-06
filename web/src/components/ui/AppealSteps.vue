<script setup lang="ts">
/** The free, step-by-step appeal checklist — one source of truth, shown both
 * inline on a property report and on the standalone /appeal page.
 *
 * Two of the steps deep-link into the city's systems by OPA account number
 * (parcel id). On the report that comes from the route; on /appeal the visitor
 * types it in. When it's absent the links fall back to the public search page
 * so they still go somewhere useful. */
import { computed } from 'vue'
import { cityPropertyUrl, opaInquiryUrl, SITE } from '@/config/site'
import { useAppealDeadlines } from '@/composables/useAppealDeadlines'

const props = defineProps<{ parcelId?: string | null }>()
const { ready, flrPassed, appealPassed, allPassed } = useAppealDeadlines()

const CITY_SEARCH = 'https://property.phila.gov'
const cityLink = computed(() => (props.parcelId ? cityPropertyUrl(props.parcelId) : CITY_SEARCH))
// opaInquiryUrl returns the inquiry landing when there's no account number yet.
const inquiryLink = computed(() => opaInquiryUrl(props.parcelId))
</script>

<template>
  <div class="rounded-lg bg-brand-50 p-4 text-body-sm text-[#2c3a4d]">
    <h3 class="text-body-sm font-extrabold text-brand-900">
      {{ !ready ? 'Check your record and review the deadlines' : allPassed ? 'Check your record and review past deadlines' : 'How to act on this (all free)' }}
    </h3>
    <p v-if="allPassed" class="mt-2">
      The Tax Year {{ SITE.assessmentTaxYear }} review and appeal deadlines have passed.
      Use the City’s links below for current guidance.
    </p>
    <ol class="mt-2 list-decimal space-y-1.5 pl-5">
      <li>
        Check the facts on your record at
        <a :href="cityLink" rel="noopener" class="font-bold text-brand-600 underline"
          >property.phila.gov</a
        >.
      </li>
      <li>
        A fact is wrong? Tell OPA through the
        <a :href="inquiryLink" rel="noopener" class="font-bold text-brand-600 underline"
          >property inquiry page</a
        >.
      </li>
      <li>
        <template v-if="!ready">Tax Year {{ SITE.assessmentTaxYear }} deadline for a </template>
        <template v-else-if="flrPassed">
          The Tax Year {{ SITE.assessmentTaxYear }} deadline for a
        </template>
        <template v-else>Disagree with the value itself? Ask OPA for a </template>
        <a :href="SITE.flrUrl" rel="noopener" class="font-bold text-brand-600 underline"
          >First Level Review (FLR)</a
        ><template v-if="!ready">: {{ SITE.flrDeadlineText }}. Check the City’s current guidance.</template>
        <template v-else-if="flrPassed"> was {{ SITE.flrDeadlineText }}.</template>
        <template v-else>
          by {{ SITE.flrDeadlineText }}. The form comes in the mail with your new assessment notice,
          or you can request one from OPA.
        </template>
      </li>
      <li>
        <template v-if="!ready">
          Tax Year {{ SITE.assessmentTaxYear }} formal appeal deadline with the
          <strong>Board of Revision of Taxes (BRT)</strong>: {{ SITE.appealDeadlineText }}.
          See the
        </template>
        <template v-else-if="appealPassed">
          The Tax Year {{ SITE.assessmentTaxYear }} deadline for a formal appeal to the
          <strong>Board of Revision of Taxes (BRT)</strong> was {{ SITE.appealDeadlineText }}.
          See the
        </template>
        <template v-else>
          To challenge the value, file a formal appeal with the
          <strong>Board of Revision of Taxes (BRT)</strong> by {{ SITE.appealDeadlineText }}.
          You do not need to wait for a First Level Review. Get the
        </template>
        <a :href="SITE.appealFormsUrl" rel="noopener" class="font-bold text-brand-600 underline"
          >BRT appeal forms and documents</a
        >.
      </li>
      <li>
        {{ !ready || allPassed ? 'Keep' : 'Bring' }} your report from this site, photos, and any repair
        estimates as evidence.
      </li>
    </ol>
    <p class="no-print mt-3">
      Details:
      <a
        href="https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/"
        rel="noopener"
        class="font-bold text-brand-600 underline"
        >phila.gov: appeal a property assessment</a
      >
    </p>
  </div>
</template>
