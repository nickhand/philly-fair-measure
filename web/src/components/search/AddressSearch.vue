<script setup lang="ts">
/** Address autocomplete following the WAI-ARIA combobox pattern:
 * role=combobox input + role=listbox popup, full keyboard support,
 * aria-activedescendant tracking, results announced via aria-live.
 * SCRIPT IS TESTED — the design pass (handoff) ports classes/markup only;
 * behavior, ids, and ARIA structure are unchanged. */
import { computed, ref, useId } from 'vue'
import { useSearch } from '@/composables/useSearch'
import { money } from '@/utils/format'
import type { SearchHit } from '@/api/types'

const props = withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })
const emit = defineEmits<{ select: [hit: SearchHit] }>()

const { hits, loading, error, query, reset } = useSearch()
const text = ref('')
const open = ref(false)
const active = ref(-1)
const inputEl = ref<HTMLInputElement | null>(null)
const baseId = useId()
const listboxId = `${baseId}-listbox`

const activeId = computed(() =>
  active.value >= 0 ? `${baseId}-opt-${active.value}` : undefined,
)

function onInput(e: Event) {
  text.value = (e.target as HTMLInputElement).value
  active.value = -1
  open.value = true
  query(text.value)
}

function choose(hit: SearchHit) {
  text.value = hit.address
  open.value = false
  reset()
  emit('select', hit)
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value && ['ArrowDown', 'ArrowUp'].includes(e.key)) {
    open.value = true
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = Math.min(active.value + 1, hits.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (e.key === 'Enter') {
    const hit = hits.value[active.value] ?? hits.value[0]
    if (open.value && hit) {
      e.preventDefault()
      choose(hit)
    }
  } else if (e.key === 'Escape') {
    open.value = false
    active.value = -1
  }
}

function onBlur() {
  // Delay so option mousedown/click wins over blur-close.
  setTimeout(() => (open.value = false), 150)
}

function onCheck() {
  const hit = hits.value[0]
  if (hit) choose(hit)
  else inputEl.value?.focus()
}

/** Bold the matched prefix in each option ("108 ELF|reths aly"). */
function prefixLen(address: string): number {
  const needle = text.value.trim().toUpperCase()
  return needle && address.toUpperCase().startsWith(needle) ? needle.length : 0
}

const showList = computed(() => open.value && text.value.trim().length >= 2)
</script>

<template>
  <div class="relative">
    <label :for="`${baseId}-input`" class="sr-only">Search your street address</label>
    <div class="flex gap-2">
      <div
        class="flex h-12 min-w-0 flex-1 items-center gap-2.5 rounded-[9px] border-[1.5px] border-[#b8c4d2] bg-white px-3.5 transition-colors duration-[var(--duration-fast)] focus-within:border-2 focus-within:border-brand-600 focus-within:ring-[3px] focus-within:ring-brand-100"
        :class="props.compact ? 'shadow-float border-transparent' : ''"
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#5d6b7c" stroke-width="2.2" stroke-linecap="round" aria-hidden="true" class="shrink-0"><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></svg>
        <input
          :id="`${baseId}-input`"
          ref="inputEl"
          :value="text"
          role="combobox"
          aria-autocomplete="list"
          :aria-expanded="showList"
          :aria-controls="listboxId"
          :aria-activedescendant="activeId"
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          enterkeyhint="search"
          type="text"
          placeholder="Enter your street address, like 1234 Market St"
          class="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
          @input="onInput"
          @keydown="onKeydown"
          @focus="open = true"
          @blur="onBlur"
        />
      </div>
      <button
        v-if="!props.compact"
        type="button"
        class="h-12 shrink-0 rounded-[9px] bg-brand-600 px-5 text-[15px] font-bold text-white hover:bg-brand-700"
        @click="onCheck"
      >
        Check
      </button>
    </div>

    <ul
      v-show="showList"
      :id="listboxId"
      role="listbox"
      aria-label="Matching addresses"
      class="absolute left-0 right-0 top-[54px] z-20 max-h-80 overflow-auto rounded-[9px] border border-line bg-white shadow-popover"
    >
      <li v-if="loading" class="px-4 py-3 text-sm text-muted" role="presentation">
        Searching…
      </li>
      <li v-else-if="error" class="px-4 py-3 text-sm text-over" role="presentation">
        {{ error }}
      </li>
      <li v-else-if="hits.length === 0" class="p-4" role="presentation">
        <div class="flex items-start gap-2.5">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#8593a4" stroke-width="2.2" stroke-linecap="round" aria-hidden="true" class="mt-0.5 shrink-0"><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></svg>
          <div>
            <p class="text-sm font-bold text-ink">No matches yet.</p>
            <p class="mt-1 text-[12.5px] leading-relaxed text-muted">
              Use your street address, like “1234 Market St”. Leave out “St” or “Ave” if you’re
              not sure.
            </p>
          </div>
        </div>
      </li>
      <li
        v-for="(hit, i) in hits"
        v-else
        :id="`${baseId}-opt-${i}`"
        :key="hit.parcel_id"
        role="option"
        :aria-selected="i === active"
        class="flex cursor-pointer items-center gap-2.5 border-t border-line-faint px-3.5 py-3 text-sm first:border-t-0"
        :class="i === active ? 'bg-brand-50 text-ink' : 'text-body'"
        @mousedown.prevent="choose(hit)"
        @mousemove="active = i"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" :stroke="i === active ? '#0f4d90' : '#8593a4'" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0"><path d="M4 11 12 4l8 7" /><path d="M6 10v9h12v-9" /></svg>
        <span class="min-w-0 flex-1 truncate font-medium text-ink">
          <template v-if="prefixLen(hit.address)">
            <strong class="font-bold">{{ hit.address.slice(0, prefixLen(hit.address)) }}</strong
            >{{ hit.address.slice(prefixLen(hit.address)) }}
          </template>
          <template v-else>{{ hit.address }}</template>
        </span>
        <span class="shrink-0 text-[12.5px] tabular-nums text-muted">{{
          money(hit.opa_market_value)
        }}</span>
      </li>
    </ul>

    <p class="sr-only" role="status" aria-live="polite">
      {{ showList && !loading ? `${hits.length} matching addresses` : '' }}
    </p>
  </div>
</template>
