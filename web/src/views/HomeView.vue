<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
    stats.value = null // the hero still works without the counter
  }
})

function goToProperty(hit: SearchHit) {
  router.push({ name: 'property', params: { parcelId: hit.parcel_id } })
}
</script>

<template>
  <div>
    <!-- hero -->
    <div class="bg-brand-900 text-white">
      <div class="mx-auto max-w-3xl px-4 py-14 sm:py-20">
        <h1 class="text-3xl leading-tight font-extrabold sm:text-4xl">
          Is your home’s assessment fair?
        </h1>
        <p class="mt-4 max-w-xl text-lg text-brand-100">
          The city decides what your home is worth. That number sets your property tax. We built a
          free second opinion from the city’s own open data — enter your address and see how your
          assessment compares.
        </p>
        <div class="mt-8 rounded-2xl bg-white p-3 shadow-lg sm:p-4">
          <AddressSearch @select="goToProperty" />
        </div>
        <p class="mt-4 text-sm text-brand-100">
          Free for everyone. No sign-up. We don’t track you.
          <RouterLink to="/map" class="font-semibold text-white underline">
            Or explore the map →
          </RouterLink>
        </p>
      </div>
    </div>

    <!-- stats strip -->
    <div v-if="stats" class="border-b border-slate-200 bg-white">
      <dl class="mx-auto grid max-w-3xl grid-cols-1 gap-4 px-4 py-6 text-center sm:grid-cols-3">
        <div>
          <dt class="text-sm text-slate-600">Homes we checked</dt>
          <dd class="text-2xl font-extrabold text-brand-700">{{ num(stats.properties) }}</dd>
        </div>
        <div>
          <dt class="text-sm text-slate-600">Assessments that look fair</dt>
          <dd class="text-2xl font-extrabold text-brand-700">{{ num(stats.within) }}</dd>
        </div>
        <div>
          <dt class="text-sm text-slate-600">Flagged for a closer look</dt>
          <dd class="text-2xl font-extrabold text-brand-700">
            {{ num(stats.over + stats.under) }}
          </dd>
        </div>
      </dl>
    </div>

    <!-- how it works, in three steps -->
    <div class="mx-auto max-w-5xl px-4 py-12">
      <h2 class="text-2xl font-bold text-slate-900">What you’ll see</h2>
      <div class="mt-6 grid gap-4 sm:grid-cols-3">
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p aria-hidden="true" class="text-2xl">📍</p>
          <h3 class="mt-2 font-bold">Your two numbers</h3>
          <p class="mt-1 text-sm text-slate-600">
            The city’s value for your home, next to our independent estimate — built from more than
            200,000 real Philadelphia home sales.
          </p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p aria-hidden="true" class="text-2xl">⚖️</p>
          <h3 class="mt-2 font-bold">A fairness check</h3>
          <p class="mt-1 text-sm text-slate-600">
            How your assessment compares with similar homes near you — because equal homes should
            get equal treatment.
          </p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p aria-hidden="true" class="text-2xl">📝</p>
          <h3 class="mt-2 font-bold">What you can do</h3>
          <p class="mt-1 text-sm text-slate-600">
            The exact facts to check on your record, and how to ask the city to fix them — appeals
            are free.
          </p>
        </div>
      </div>

      <div class="mt-10 rounded-2xl bg-brand-50 p-5 text-sm text-slate-700 sm:p-6">
        <h2 class="font-bold text-brand-900">Built to be honest</h2>
        <p class="mt-2">
          Our model is not perfect, and we say so: every estimate comes with a range, and we publish
          exactly how the model works, what data it uses, and what it cannot see.
          <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
            >Read the methodology</RouterLink
          >.
        </p>
      </div>
    </div>
  </div>
</template>
