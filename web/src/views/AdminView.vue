<script setup lang="ts">
/** Staff worklists (leaderboards). Deliberately unlinked from public nav.
 *
 * SECURITY NOTE: the passphrase gate below is a placeholder so casual visitors
 * don't wander in — it is NOT authentication. The /api/admin endpoints must be
 * put behind real auth (or not deployed) before this app faces the internet.
 * Tracked in docs/frontend.md. */
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { LeaderRow } from '@/api/types'
import { money, pct } from '@/utils/format'

const GATE_KEY = 'pac-staff'
const unlocked = ref(false)
const phrase = ref('')
const gateError = ref(false)

const kind = ref<'over' | 'under' | 'nonuniform'>('over')
const rows = ref<LeaderRow[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

function unlock() {
  // Placeholder gate — see the security note above.
  if (phrase.value.trim() === 'philly-staff') {
    localStorage.setItem(GATE_KEY, '1')
    unlocked.value = true
    load()
  } else {
    gateError.value = true
  }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    rows.value = await api.leaderboard(kind.value, 50)
  } catch {
    error.value = 'Could not load the worklist. Is the API running with model artifacts?'
    rows.value = []
  } finally {
    loading.value = false
  }
}

function switchKind(k: 'over' | 'under' | 'nonuniform') {
  kind.value = k
  load()
}

onMounted(() => {
  unlocked.value = localStorage.getItem(GATE_KEY) === '1'
  if (unlocked.value) load()
})
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-8">
    <h1 class="text-2xl font-extrabold text-slate-900">Staff worklists</h1>

    <div v-if="!unlocked" class="mt-6 max-w-md rounded-2xl border border-slate-200 bg-white p-6">
      <p class="text-slate-700">This area is for project staff.</p>
      <form class="mt-4" @submit.prevent="unlock">
        <label for="staff-phrase" class="block text-sm font-medium text-slate-800"
          >Passphrase</label
        >
        <input
          id="staff-phrase"
          v-model="phrase"
          type="password"
          autocomplete="off"
          class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5"
        />
        <p v-if="gateError" class="mt-2 text-sm text-over" role="alert">That’s not it.</p>
        <button
          type="submit"
          class="mt-3 w-full rounded-lg bg-brand-600 py-2.5 font-bold text-white hover:bg-brand-700"
        >
          Enter
        </button>
      </form>
    </div>

    <template v-else>
      <p class="mt-1 text-sm text-slate-600">
        Review queues from the assessment screen. Ranked by confidence (screen z), model blind
        spots filtered. Verify every row against its report before acting.
      </p>

      <div class="mt-5 flex gap-1" role="tablist" aria-label="Worklist type">
        <button
          v-for="k in ['over', 'under', 'nonuniform'] as const"
          :key="k"
          role="tab"
          :aria-selected="kind === k"
          class="min-h-11 rounded-lg px-4 text-sm font-semibold"
          :class="kind === k ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-700'"
          @click="switchKind(k)"
        >
          {{ k === 'over' ? 'Over-assessed' : k === 'under' ? 'Under-assessed' : 'Non-uniform blocks' }}
        </button>
      </div>

      <p v-if="loading" class="mt-6 text-slate-600">Loading…</p>
      <p v-else-if="error" class="mt-6 text-over" role="alert">{{ error }}</p>

      <div v-else class="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-slate-200 bg-slate-50 text-slate-600">
            <tr>
              <th scope="col" class="px-3 py-2.5 font-medium">Address</th>
              <th scope="col" class="px-3 py-2.5 font-medium">City value</th>
              <th scope="col" class="px-3 py-2.5 font-medium">Model</th>
              <th v-if="kind !== 'nonuniform'" scope="col" class="px-3 py-2.5 font-medium">
                Ratio
              </th>
              <th v-if="kind !== 'nonuniform'" scope="col" class="px-3 py-2.5 font-medium">z</th>
              <th v-if="kind === 'nonuniform'" scope="col" class="px-3 py-2.5 font-medium">
                vs twins
              </th>
              <th scope="col" class="px-3 py-2.5"><span class="sr-only">Report</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.parcel_id" class="border-b border-slate-100">
              <th scope="row" class="px-3 py-2 font-medium text-slate-900">{{ r.address }}</th>
              <td class="px-3 py-2 tabular-nums">{{ money(r.opa_market_value) }}</td>
              <td class="px-3 py-2 tabular-nums">{{ money(r.model_median) }}</td>
              <td v-if="kind !== 'nonuniform'" class="px-3 py-2 tabular-nums">
                {{ r.ratio?.toFixed(1) }}×
              </td>
              <td v-if="kind !== 'nonuniform'" class="px-3 py-2 tabular-nums">
                {{ r.screen_z?.toFixed(1) }}
              </td>
              <td v-if="kind === 'nonuniform'" class="px-3 py-2 tabular-nums">
                {{ r.twin_ratio ? pct(r.twin_ratio - 1, 1) : '—' }} ({{ r.twin_n }} twins)
              </td>
              <td class="px-3 py-2">
                <RouterLink
                  :to="{ name: 'property', params: { parcelId: r.parcel_id } }"
                  class="font-medium text-brand-600 underline"
                  >report</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
