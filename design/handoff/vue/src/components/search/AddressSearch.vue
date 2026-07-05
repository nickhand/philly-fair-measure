<script setup lang="ts">
/** AddressSearch — ARIA combobox.
 * ⚠ If your existing AddressSearch has tested behavior, DO NOT swap this file
 * in — port the classes/markup styling onto your component instead. This
 * implementation follows the standard combobox pattern (role=combobox,
 * aria-expanded, aria-activedescendant, listbox/options, Arrow/Enter/Escape)
 * and assumes `api.search(q)` returning { parcel_id, address }[] — verify. */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'

const props = withDefaults(
  defineProps<{ placeholder?: string; variant?: 'hero' | 'float' }>(),
  { placeholder: 'Enter your street address, like 1234 Market St', variant: 'hero' },
)

const router = useRouter()
const q = ref('')
const results = ref<{ parcel_id: string; address: string }[]>([])
const open = ref(false)
const active = ref(-1)
const searched = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

watch(q, (val) => {
  clearTimeout(timer)
  active.value = -1
  if (val.trim().length < 3) {
    open.value = false
    searched.value = false
    return
  }
  timer = setTimeout(async () => {
    try {
      results.value = await api.search(val.trim())
    } catch {
      results.value = []
    }
    searched.value = true
    open.value = true
  }, 200)
})

function go(r: { parcel_id: string }) {
  open.value = false
  router.push(`/property/${r.parcel_id}`)
}
function onKeydown(e: KeyboardEvent) {
  if (!open.value && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    open.value = results.value.length > 0
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = Math.min(active.value + 1, results.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (e.key === 'Enter' && active.value >= 0) {
    e.preventDefault()
    go(results.value[active.value])
  } else if (e.key === 'Escape') {
    open.value = false
  }
}

/** Bold the matched prefix, like the mock. */
const matchLen = computed(() => q.value.trim().length)
</script>

<template>
  <div class="relative">
    <div class="flex gap-2">
      <div
        class="flex h-12 flex-1 items-center gap-2.5 rounded-[9px] border-[1.5px] border-[#b8c4d2] bg-white px-3.5 transition-colors duration-[var(--duration-fast)] focus-within:border-2 focus-within:border-brand-600 focus-within:ring-[3px] focus-within:ring-brand-100"
        :class="variant === 'float' ? 'shadow-float border-transparent' : ''"
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#5d6b7c" stroke-width="2.2" stroke-linecap="round" aria-hidden="true" class="shrink-0"><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></svg>
        <input
          v-model="q"
          type="text"
          role="combobox"
          aria-label="Search for a Philadelphia address"
          :aria-expanded="open"
          aria-controls="address-listbox"
          aria-autocomplete="list"
          :aria-activedescendant="active >= 0 ? `address-opt-${active}` : undefined"
          :placeholder="placeholder"
          class="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
          @keydown="onKeydown"
          @focus="open = results.length > 0 || searched"
        />
      </div>
      <button
        v-if="variant === 'hero'"
        type="button"
        class="h-12 shrink-0 rounded-[9px] bg-brand-600 px-5 text-[15px] font-bold text-white hover:bg-brand-700"
        @click="active >= 0 ? go(results[active]) : results[0] && go(results[0])"
      >
        Check
      </button>
    </div>

    <ul
      v-if="open && results.length"
      id="address-listbox"
      role="listbox"
      aria-label="Matching addresses"
      class="absolute left-0 right-0 top-[54px] z-10 overflow-hidden rounded-[9px] border border-line bg-white shadow-popover"
    >
      <li
        v-for="(r, i) in results"
        :id="`address-opt-${i}`"
        :key="r.parcel_id"
        role="option"
        :aria-selected="i === active"
        class="flex cursor-pointer items-center gap-2.5 border-t border-line-faint px-3.5 py-3 text-sm first:border-t-0"
        :class="i === active ? 'bg-brand-50 text-ink' : 'text-body'"
        @mousedown.prevent="go(r)"
        @mousemove="active = i"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" :stroke="i === active ? '#0f4d90' : '#8593a4'" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0"><path d="M4 11 12 4l8 7" /><path d="M6 10v9h12v-9" /></svg>
        <span><strong>{{ r.address.slice(0, matchLen) }}</strong>{{ r.address.slice(matchLen) }}</span>
      </li>
    </ul>

    <!-- no matches -->
    <div
      v-else-if="open && searched && !results.length"
      class="absolute left-0 right-0 top-[54px] z-10 rounded-[9px] border border-line bg-white p-4 shadow-popover"
    >
      <div class="flex items-start gap-2.5">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#8593a4" stroke-width="2.2" stroke-linecap="round" aria-hidden="true" class="mt-0.5 shrink-0"><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></svg>
        <div>
          <p class="text-sm font-bold text-ink">No matches for “{{ q }}”</p>
          <p class="mt-1 text-[12.5px] leading-relaxed text-muted">
            Try just the house number and street name, like
            <strong class="text-body">108 Elfreths</strong>. Leave out “St” or “Ave” if you’re not sure.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
