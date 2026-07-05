<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { FileText, MapPin, Scale } from 'lucide-vue-next'
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

const cards = [
  {
    icon: MapPin,
    title: 'Your two numbers',
    body: 'The city’s value for your home, next to our independent estimate — built from more than 200,000 real Philadelphia home sales.',
  },
  {
    icon: Scale,
    title: 'A fairness check',
    body: 'How your assessment compares with similar homes near you — because equal homes should get equal treatment.',
  },
  {
    icon: FileText,
    title: 'What you can do',
    body: 'The exact facts to check on your record, and how to ask the city to fix them — appeals are free.',
  },
]
</script>

<template>
  <div>
    <!-- hero -->
    <div class="on-dark bg-brand-900 text-white">
      <div class="mx-auto max-w-3xl px-4 py-14 sm:py-20">
        <h1 class="font-display text-3xl leading-tight font-bold sm:text-4xl">
          Is your home’s assessment fair?
        </h1>
        <p class="mt-4 max-w-xl text-lg text-brand-100">
          The city decides what your home is worth. That number sets your property tax. We built a
          free second opinion from the city’s own open data — enter your address and see how your
          assessment compares.
        </p>
        <div class="mt-8 rounded-xl bg-white p-3 shadow-float sm:p-4">
          <AddressSearch @select="goToProperty" />
        </div>
        <p class="mt-4 text-body-sm text-brand-100">
          Free for everyone. No sign-up. We don’t track you.
          <RouterLink to="/map" class="font-semibold text-white underline">
            Or explore the map →
          </RouterLink>
        </p>
      </div>
    </div>

    <!-- stats strip -->
    <div v-if="stats" class="border-b border-line bg-white">
      <dl class="mx-auto grid max-w-3xl grid-cols-1 gap-4 px-4 py-6 text-center sm:grid-cols-3">
        <div>
          <dt class="text-body-sm text-muted">Homes we checked</dt>
          <dd class="money text-2xl font-extrabold text-brand-600">{{ num(stats.properties) }}</dd>
        </div>
        <div>
          <dt class="text-body-sm text-muted">Assessments that look fair</dt>
          <dd class="money text-2xl font-extrabold text-brand-600">{{ num(stats.within) }}</dd>
        </div>
        <div>
          <dt class="text-body-sm text-muted">Flagged for a closer look</dt>
          <dd class="money text-2xl font-extrabold text-brand-600">
            {{ num(stats.over + stats.under) }}
          </dd>
        </div>
      </dl>
    </div>

    <!-- how it works, in three steps -->
    <div class="mx-auto max-w-5xl px-4 py-12">
      <h2 class="text-2xl font-bold text-ink">What you’ll see</h2>
      <div class="mt-6 grid gap-4 sm:grid-cols-3">
        <div
          v-for="card in cards"
          :key="card.title"
          class="rounded-lg border border-line-soft bg-white p-5"
        >
          <span
            class="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50"
            aria-hidden="true"
          >
            <component :is="card.icon" :size="20" class="text-brand-600" />
          </span>
          <h3 class="mt-3 font-bold text-ink">{{ card.title }}</h3>
          <p class="mt-1 text-body-sm text-body">{{ card.body }}</p>
        </div>
      </div>

      <div class="mt-10 rounded-lg border border-line-soft bg-brand-50 p-5 text-body-sm sm:p-6">
        <h2 class="font-bold text-brand-900">Built to be honest</h2>
        <p class="mt-2 text-body">
          Our model is not perfect, and we say so: every estimate comes with a range, and we publish
          exactly how the model works, what data it uses, and what it cannot see.
          <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
            >Read the methodology</RouterLink
          >
          or check
          <RouterLink to="/trust" class="font-semibold text-brand-600 underline"
            >the proof that our numbers hold up</RouterLink
          >.
        </p>
      </div>
    </div>
  </div>
</template>
