<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <a class="skip-link" href="#main">Skip to main content</a>

  <!-- flag-gold top rule: part of the identity, on every page -->
  <div class="h-1 bg-gold" aria-hidden="true"></div>

  <header class="border-b border-line bg-white">
    <nav
      class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-2.5"
      aria-label="Main"
    >
      <RouterLink to="/" class="flex items-center gap-2.5" aria-label="Fair Measure — home">
        <!-- the mark: the IntervalStrip as identity (band + estimate tick + gold city dot) -->
        <svg width="34" height="26" viewBox="0 0 40 31" aria-hidden="true" class="shrink-0">
          <rect x="0" y="10" width="40" height="11" rx="5.5" fill="#b9d2ee" />
          <rect x="16.5" y="3" width="6" height="25" rx="2" fill="#0f4d90" />
          <circle cx="33.5" cy="4.5" r="4.5" fill="#f3c613" />
        </svg>
        <span class="leading-none">
          <span class="block text-[17px] font-extrabold tracking-tight text-ink">Fair Measure</span>
          <span class="mt-0.5 block text-[9px] font-semibold tracking-[0.22em] text-muted"
            >PHILADELPHIA</span
          >
        </span>
      </RouterLink>
      <div class="flex items-center gap-1 text-body-sm font-semibold sm:gap-2">
        <RouterLink
          to="/map"
          class="rounded-sm px-3 py-2 text-body hover:bg-paper"
          active-class="bg-brand-50 text-brand-600"
          >Map</RouterLink
        >
        <RouterLink
          to="/methodology"
          class="rounded-sm px-3 py-2 text-body hover:bg-paper"
          active-class="bg-brand-50 text-brand-600"
          >How it works</RouterLink
        >
      </div>
    </nav>
  </header>

  <main id="main" class="min-h-[70vh]">
    <RouterView />
  </main>

  <footer class="mt-12 border-t border-line bg-white">
    <div class="mx-auto max-w-5xl space-y-3 px-4 py-8 text-body-sm text-muted">
      <p class="flex items-center gap-2">
        <svg width="26" height="20" viewBox="0 0 40 31" aria-hidden="true" class="shrink-0">
          <rect x="0" y="10" width="40" height="11" rx="5.5" fill="#b9d2ee" />
          <rect x="16.5" y="3" width="6" height="25" rx="2" fill="#0f4d90" />
          <circle cx="33.5" cy="4.5" r="4.5" fill="#f3c613" />
        </svg>
        <strong class="text-ink">Fair Measure</strong>
      </p>
      <p>
        Fair Measure is a free, independent tool. It is not run by the City of Philadelphia. It is
        built only from the city’s own open data.
      </p>
      <p>
        Our estimates are not appraisals. This site is not legal or tax advice. Before you act,
        check the city’s records at
        <a
          href="https://property.phila.gov"
          class="font-semibold text-brand-600 underline"
          rel="noopener"
          >property.phila.gov</a
        >.
      </p>
      <p>
        We do not track you. No ads, no cookies, no analytics.
        <RouterLink to="/methodology" class="font-semibold text-brand-600 underline"
          >Read exactly how this works</RouterLink
        >
        or see
        <RouterLink to="/trust" class="font-semibold text-brand-600 underline"
          >why you can trust these numbers</RouterLink
        >.
      </p>
    </div>
  </footer>
</template>
