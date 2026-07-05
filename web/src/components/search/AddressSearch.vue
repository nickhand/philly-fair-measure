<script setup lang="ts">
/** Address autocomplete following the WAI-ARIA combobox pattern:
 * role=combobox input + role=listbox popup, full keyboard support,
 * aria-activedescendant tracking, results announced via aria-live. */
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

const showList = computed(() => open.value && text.value.trim().length >= 2)
</script>

<template>
  <div class="relative">
    <label
      :for="`${baseId}-input`"
      :class="props.compact ? 'sr-only' : 'mb-2 block font-medium text-slate-800'"
    >
      Search your street address
    </label>
    <div class="relative">
      <span aria-hidden="true" class="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-slate-400">
        🔍
      </span>
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
        placeholder="Try “1234 Market St”"
        class="w-full rounded-xl border border-slate-300 bg-white py-3.5 pr-4 pl-11 text-base shadow-sm placeholder:text-slate-400 focus:border-brand-600"
        @input="onInput"
        @keydown="onKeydown"
        @focus="open = true"
        @blur="onBlur"
      />
    </div>

    <ul
      v-show="showList"
      :id="listboxId"
      role="listbox"
      aria-label="Matching addresses"
      class="absolute z-20 mt-2 max-h-80 w-full overflow-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
    >
      <li v-if="loading" class="px-4 py-3 text-sm text-slate-500" role="presentation">
        Searching…
      </li>
      <li v-else-if="error" class="px-4 py-3 text-sm text-over" role="presentation">
        {{ error }}
      </li>
      <li
        v-else-if="hits.length === 0"
        class="px-4 py-3 text-sm text-slate-500"
        role="presentation"
      >
        No matches yet. Use your street address, like “1234 Market St”.
      </li>
      <li
        v-for="(hit, i) in hits"
        v-else
        :id="`${baseId}-opt-${i}`"
        :key="hit.parcel_id"
        role="option"
        :aria-selected="i === active"
        class="flex cursor-pointer items-baseline justify-between gap-3 px-4 py-3"
        :class="i === active ? 'bg-brand-50' : 'hover:bg-slate-50'"
        @mousedown.prevent="choose(hit)"
        @mousemove="active = i"
      >
        <span class="font-medium text-slate-900">{{ hit.address }}</span>
        <span class="shrink-0 text-sm text-slate-500">{{ money(hit.opa_market_value) }}</span>
      </li>
    </ul>

    <p class="sr-only" role="status" aria-live="polite">
      {{ showList && !loading ? `${hits.length} matching addresses` : '' }}
    </p>
  </div>
</template>
