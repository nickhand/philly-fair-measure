<script setup lang="ts">
/** Address autocomplete following the WAI-ARIA combobox pattern:
 * role=combobox input + role=listbox popup, full keyboard support,
 * aria-activedescendant tracking, results announced via aria-live.
 * (Design pass restyled classes/icons only — behavior and ARIA untouched.) */
import { computed, ref, useId } from 'vue'
import { House, Search } from 'lucide-vue-next'
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
    <label
      :for="`${baseId}-input`"
      :class="props.compact ? 'sr-only' : 'mb-2 block font-semibold text-ink'"
    >
      Search your street address
    </label>
    <div class="flex gap-2">
      <div class="relative min-w-0 flex-1">
        <Search
          aria-hidden="true"
          :size="18"
          class="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-muted"
        />
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
          class="h-12 w-full rounded-md border-[1.5px] border-[#b8c4d2] bg-white pr-3 pl-10 text-body text-ink placeholder:text-faint focus:border-2 focus:border-brand-600 focus:ring-[3px] focus:ring-brand-100 focus:outline-none"
          @input="onInput"
          @keydown="onKeydown"
          @focus="open = true"
          @blur="onBlur"
        />
      </div>
      <button
        v-if="!props.compact"
        type="button"
        class="h-12 shrink-0 rounded-md bg-brand-600 px-5 font-bold text-white hover:bg-brand-700"
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
      class="absolute z-20 mt-2 max-h-80 w-full overflow-auto rounded-md border border-line-soft bg-white py-1 shadow-popover"
    >
      <li v-if="loading" class="px-4 py-3 text-body-sm text-muted" role="presentation">
        Searching…
      </li>
      <li v-else-if="error" class="px-4 py-3 text-body-sm text-over" role="presentation">
        {{ error }}
      </li>
      <li v-else-if="hits.length === 0" class="px-4 py-4" role="presentation">
        <p class="font-bold text-ink">No matches yet.</p>
        <p class="mt-0.5 text-body-sm text-muted">
          Use your street address, like “1234 Market St”.
        </p>
      </li>
      <li
        v-for="(hit, i) in hits"
        v-else
        :id="`${baseId}-opt-${i}`"
        :key="hit.parcel_id"
        role="option"
        :aria-selected="i === active"
        class="flex cursor-pointer items-center gap-2.5 px-3.5 py-3"
        :class="i === active ? 'bg-brand-50' : 'hover:bg-paper'"
        @mousedown.prevent="choose(hit)"
        @mousemove="active = i"
      >
        <House aria-hidden="true" :size="16" class="shrink-0 text-muted" />
        <span class="min-w-0 flex-1 truncate font-medium text-ink">
          <template v-if="prefixLen(hit.address)">
            <strong class="font-bold">{{ hit.address.slice(0, prefixLen(hit.address)) }}</strong
            >{{ hit.address.slice(prefixLen(hit.address)) }}
          </template>
          <template v-else>{{ hit.address }}</template>
        </span>
        <span class="money shrink-0 text-body-sm text-muted">{{
          money(hit.opa_market_value)
        }}</span>
      </li>
    </ul>

    <p class="sr-only" role="status" aria-live="polite">
      {{ showList && !loading ? `${hits.length} matching addresses` : '' }}
    </p>
  </div>
</template>
