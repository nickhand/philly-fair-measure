<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <a class="skip-link" href="#main">Skip to main content</a>

  <header class="border-b border-slate-200 bg-white">
    <nav
      class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3"
      aria-label="Main"
    >
      <RouterLink to="/" class="flex items-center gap-2 font-bold text-brand-700">
        <span aria-hidden="true" class="text-xl">🏠</span>
        <span>Philly Assessment Check</span>
      </RouterLink>
      <div class="flex items-center gap-1 text-sm font-medium sm:gap-2">
        <RouterLink
          to="/map"
          class="rounded px-3 py-2 text-slate-700 hover:bg-slate-100"
          active-class="bg-brand-50 text-brand-700"
          >Map</RouterLink
        >
        <RouterLink
          to="/methodology"
          class="rounded px-3 py-2 text-slate-700 hover:bg-slate-100"
          active-class="bg-brand-50 text-brand-700"
          >How it works</RouterLink
        >
      </div>
    </nav>
  </header>

  <main id="main" class="min-h-[70vh]">
    <RouterView />
  </main>

  <footer class="mt-12 border-t border-slate-200 bg-white">
    <div class="mx-auto max-w-5xl space-y-3 px-4 py-8 text-sm text-slate-600">
      <p>
        <strong>Philly Assessment Check</strong> is a free, independent tool. It is not run by the
        City of Philadelphia. It is built only from the city’s own open data.
      </p>
      <p>
        Our estimates are not appraisals. This site is not legal or tax advice. Before you act,
        check the city’s records at
        <a
          href="https://property.phila.gov"
          class="font-medium text-brand-600 underline"
          rel="noopener"
          >property.phila.gov</a
        >.
      </p>
      <p>
        We do not track you. No ads, no cookies, no analytics.
        <RouterLink to="/methodology" class="font-medium text-brand-600 underline"
          >Read exactly how this works</RouterLink
        >.
      </p>
    </div>
  </footer>
</template>
