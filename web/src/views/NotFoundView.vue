<script setup lang="ts">
import { House } from 'lucide-vue-next'
</script>

<template>
  <div class="mx-auto max-w-xl px-4 py-16 text-center">
    <span
      class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-brand-50"
      aria-hidden="true"
    >
      <House :size="24" class="text-brand-600" />
    </span>
    <h1 class="mt-4 text-3xl font-extrabold text-ink">Page not found</h1>
    <p class="mt-3 text-body">That page doesn’t exist. Try searching for your address.</p>
    <RouterLink
      to="/"
      class="mt-6 inline-block rounded-md bg-brand-600 px-6 py-3 font-bold text-white hover:bg-brand-700"
    >
      Back to search
    </RouterLink>
  </div>
</template>
