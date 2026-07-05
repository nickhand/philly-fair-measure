<script setup lang="ts">
/** Home — hero + search, three promise cards, citywide counters, honesty note.
 * TODO before ship: replace the three counter values with real figures from
 * the API/build step (the mocks used sample numbers). */
import AddressSearch from '@/components/search/AddressSearch.vue'

// TODO: wire to real citywide stats endpoint if available.
const counters = [
  { value: '579,000', label: 'homes checked citywide' },
  { value: '1 in 5', label: 'may be over-assessed' },
  { value: '$0', label: 'to check or appeal' },
]

const promises = [
  {
    icon: 'scale',
    title: 'A clear answer',
    body: 'Fair, may be too high, or lower than our estimate — with the evidence behind it.',
  },
  {
    icon: 'interval',
    title: 'The full picture',
    body: 'Our estimate range, how neighbors are assessed, and ten years of history.',
  },
  {
    icon: 'document',
    title: 'What to do next',
    body: 'If something looks off, the free steps to fix the record or appeal — no lawyer needed.',
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
      <p class="mx-auto mt-2.5 max-w-[520px] text-[15px] leading-relaxed text-body sm:mt-3.5 sm:text-base">
        Type your address. See how the city’s value compares with an independent estimate — free, no sign-up.
      </p>
      <div class="mx-auto mt-4 max-w-[560px] text-left sm:mt-5">
        <AddressSearch />
      </div>
    </div>

    <!-- three promises -->
    <div class="mx-auto mt-4 grid max-w-5xl gap-3 px-4 sm:mt-6 sm:grid-cols-3 sm:gap-4">
      <div
        v-for="p in promises"
        :key="p.title"
        class="flex gap-3 rounded-lg border border-line-soft bg-white p-4 sm:block"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px] bg-brand-50" aria-hidden="true">
          <svg v-if="p.icon === 'scale'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="3" x2="12" y2="21" /><line x1="4" y1="6" x2="20" y2="6" /><path d="M6 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><path d="M18 6l-2.8 6a2.9 2.9 0 0 0 5.6 0Z" /><line x1="8" y1="21" x2="16" y2="21" /></svg>
          <svg v-else-if="p.icon === 'interval'" width="18" height="12" viewBox="0 0 26 17"><rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" /><rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" /><circle cx="21" cy="3" r="2.6" fill="#c2410c" /></svg>
          <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2.5h9l4 4V21a.9.9 0 0 1-.9.9H6a.9.9 0 0 1-.9-.9V3.4a.9.9 0 0 1 .9-.9Z" /><line x1="9" y1="12" x2="15" y2="12" /><line x1="9" y1="16" x2="15" y2="16" /></svg>
        </div>
        <div>
          <h2 class="text-[14.5px] font-bold text-ink sm:mt-2.5 sm:text-[15px]">{{ p.title }}</h2>
          <p class="mt-0.5 text-[13px] leading-relaxed text-muted sm:mt-1">{{ p.body }}</p>
        </div>
      </div>
    </div>

    <!-- counters + honesty -->
    <div class="mx-auto mt-4 grid max-w-5xl gap-3 px-4 sm:grid-cols-[1.1fr_1fr] sm:gap-4">
      <div class="flex items-center justify-between gap-3 rounded-lg border border-line-soft bg-white px-4 py-3.5 text-center sm:px-5">
        <template v-for="(c, i) in counters" :key="c.label">
          <div v-if="i > 0" class="w-px self-stretch bg-line-soft" aria-hidden="true"></div>
          <div>
            <p class="text-lg font-extrabold tabular-nums text-ink sm:text-xl">{{ c.value }}</p>
            <p class="mt-0.5 text-[10.5px] leading-tight text-muted sm:text-[11px]">{{ c.label }}</p>
          </div>
        </template>
      </div>
      <div class="flex items-center gap-2.5 rounded-lg border border-[#d8e4f2] bg-[#eef4fb] px-4 py-3.5">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0f4d90" stroke-width="2" stroke-linecap="round" aria-hidden="true" class="shrink-0"><circle cx="12" cy="12" r="9.5" /><line x1="12" y1="11" x2="12" y2="16.5" /><circle cx="12" cy="7.5" r="0.6" fill="#0f4d90" /></svg>
        <p class="text-[12.5px] leading-relaxed text-body">
          We are independent — not run by the City of Philadelphia. Everything here is built from the
          city’s own open data, and we show our work.
          <RouterLink to="/methodology" class="font-semibold text-brand-600 underline">Read exactly how this works</RouterLink>.
        </p>
      </div>
    </div>
  </div>
</template>
