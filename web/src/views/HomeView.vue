<script setup lang="ts">
/** Home — hero + search, three promise cards, citywide counters, honesty note.
 * Handoff SFC wired to real citywide figures from /api/stats (the mocks used
 * sample numbers; "1 in 5 may be over-assessed" did NOT survive contact with
 * the data and was replaced by the real flagged count). */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AddressSearch from '@/components/search/AddressSearch.vue'
import { api } from '@/api/client'
import { num } from '@/utils/format'
import type { SearchHit, Stats } from '@/api/types'

const router = useRouter()
const stats = ref<Stats | null>(null)

onMounted(async () => {
  try {
    stats.value = await api.stats()
  } catch {
    stats.value = null // the hero still works without the counters
  }
})

function goToProperty(hit: SearchHit) {
  router.push({ name: 'property', params: { parcelId: hit.parcel_id } })
}

/** Always renders — a null value shows a spinner until /api/stats responds,
 * so the layout never collapses when the API is slow or down. */
const counters = computed<{ value: string | null; label: string }[]>(() => {
  const s = stats.value
  return [
    { value: s ? num(s.properties) : null, label: 'homes we valued citywide' },
    { value: s ? num(s.over + s.under) : null, label: 'flagged outside our range' },
    { value: s ? num(s.watch) : null, label: 'more worth a closer look' },
    { value: '$0', label: 'to check or appeal' },
  ]
})

const promises = [
  {
    icon: 'scale',
    title: 'A clear answer',
    body: 'A plain answer: fair, too high, or too low, with the evidence behind it.',
  },
  {
    icon: 'interval',
    title: 'The full picture',
    body: 'You see our estimate range, how nearby homes are assessed, and ten years of history.',
  },
  {
    icon: 'document',
    title: 'What to do next',
    body: 'If something looks off, we show the free steps to fix your record or appeal. You do not need a lawyer.',
  },
]
</script>

<template>
  <div class="bg-paper pb-6">
    <!-- hero -->
    <div class="border-b border-line bg-white px-4 py-7 sm:py-13 sm:text-center">
      <h1 class="mx-auto max-w-[600px] font-display text-[29px] font-bold leading-tight tracking-tight text-ink sm:text-[40px]" style="text-wrap: pretty">
        Is your home’s assessment fair?
      </h1>
      <p class="mx-auto mt-2.5 max-w-[520px] text-base leading-relaxed text-body sm:mt-3.5 sm:text-base">
        Type your address. See how the city’s value compares with an independent estimate. It’s free, with no sign-up.
      </p>
      <div class="mx-auto mt-4 max-w-[560px] text-left sm:mt-5">
        <AddressSearch @select="goToProperty" />
      </div>
    </div>

    <!-- citywide counters: the front-page numbers, prominent and always present -->
    <div class="mx-auto mt-4 max-w-5xl px-4 sm:mt-6">
      <dl
        class="grid grid-cols-2 gap-4 rounded-lg border border-line-soft bg-white px-4 py-5 text-center sm:grid-cols-4 sm:px-6"
      >
        <div v-for="c in counters" :key="c.label">
          <dd class="money text-3xl font-extrabold tracking-tight text-brand-600">
            <span v-if="c.value === null" role="status" aria-label="Loading" class="inline-flex h-8 items-center justify-center">
              <svg class="h-6 w-6 animate-spin text-brand-300" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" stroke-opacity="0.3" />
                <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
              </svg>
            </span>
            <template v-else>{{ c.value }}</template>
          </dd>
          <dt class="mt-1 text-body-sm text-muted">{{ c.label }}</dt>
        </div>
      </dl>
      <p class="mt-2 text-center text-body-sm">
        <RouterLink to="/findings" class="font-semibold text-brand-600 underline"
          >See what ten years of assessments add up to →</RouterLink
        >
      </p>
    </div>

    <!-- three promises -->
    <div class="mx-auto mt-4 grid max-w-5xl gap-3 px-4 sm:grid-cols-3 sm:gap-4">
      <div
        v-for="p in promises"
        :key="p.title"
        class="flex gap-3 rounded-lg border border-line-soft bg-white p-4 sm:block"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px] bg-brand-50" aria-hidden="true">
          <svg v-if="p.icon === 'scale'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="3" x2="12" y2="21" /><line x1="4" y1="6" x2="20" y2="6" /><path d="M6 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><path d="M18 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><line x1="8" y1="21" x2="16" y2="21" /></svg>
          <svg v-else-if="p.icon === 'interval'" width="18" height="12" viewBox="0 0 26 17"><rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" /><rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" /><circle cx="21" cy="3" r="2.6" fill="#c2410c" /></svg>
          <svg v-else width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2.5h9l4 4V21a.9.9 0 0 1-.9.9H6a.9.9 0 0 1-.9-.9V3.4a.9.9 0 0 1 .9-.9Z" /><line x1="9" y1="12" x2="15" y2="12" /><line x1="9" y1="16" x2="15" y2="16" /></svg>
        </div>
        <div>
          <h2 class="text-base font-bold text-ink sm:mt-2.5 sm:text-body">{{ p.title }}</h2>
          <p class="mt-0.5 text-body-sm leading-relaxed text-muted sm:mt-1">{{ p.body }}</p>
        </div>
      </div>
    </div>

    <!-- honesty note -->
    <div class="mx-auto mt-4 max-w-5xl px-4">
      <div class="flex items-center gap-2.5 rounded-lg border border-[#d8e4f2] bg-[#eef4fb] px-4 py-3.5">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="2" stroke-linecap="round" aria-hidden="true" class="shrink-0"><circle cx="12" cy="12" r="9.5" /><line x1="12" y1="11" x2="12" y2="16.5" /><circle cx="12" cy="7.5" r="0.6" fill="#0f4d90" /></svg>
        <p class="text-caption leading-relaxed text-body">
          We are independent. We are not run by the City of Philadelphia. Everything here is built
          from the city’s own open data, and we show our work.
          <RouterLink to="/methodology" class="font-semibold text-brand-600 underline">Read exactly how this works</RouterLink>
          or see
          <RouterLink to="/trust" class="font-semibold text-brand-600 underline">why you can trust these numbers</RouterLink>.
        </p>
      </div>
    </div>
  </div>
</template>
