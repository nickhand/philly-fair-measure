<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <a class="skip-link" href="#main">Skip to main content</a>

  <!-- flag-gold rule: the one place gold touches the chrome -->
  <div class="h-1 bg-gold" aria-hidden="true"></div>

  <header class="border-b border-line bg-white">
    <nav
      class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3"
      aria-label="Main"
    >
      <RouterLink to="/" class="flex items-center gap-2.5">
        <svg width="26" height="17" viewBox="0 0 26 17" aria-hidden="true">
          <rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" />
          <rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" />
          <circle cx="21" cy="3" r="2.6" fill="#f3c613" />
        </svg>
        <span class="flex flex-col leading-none">
          <span class="text-base font-extrabold tracking-tight text-ink">Fair Measure</span>
          <span class="mt-0.5 text-[9.5px] font-semibold uppercase tracking-[0.09em] text-muted">Philadelphia</span>
        </span>
      </RouterLink>
      <div class="flex items-center gap-1 text-sm font-semibold sm:gap-2">
        <RouterLink
          to="/map"
          class="rounded-sm px-3 py-2 text-[#334155] hover:bg-brand-50"
          active-class="bg-brand-50 text-brand-600"
          >Map</RouterLink
        >
        <RouterLink
          to="/methodology"
          class="rounded-sm px-3 py-2 text-[#334155] hover:bg-brand-50"
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
    <div class="mx-auto max-w-5xl space-y-3 px-4 py-8 text-sm text-muted">
      <div class="flex items-center gap-2">
        <svg width="22" height="14" viewBox="0 0 26 17" aria-hidden="true">
          <rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" />
          <rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" />
          <circle cx="21" cy="3" r="2.6" fill="#f3c613" />
        </svg>
        <span class="text-sm font-extrabold text-ink">Fair Measure</span>
      </div>
      <p>
        <strong class="text-body">Fair Measure</strong> is a free, independent tool. It is not run by the
        City of Philadelphia. It is built only from the city’s own open data.
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
        >.
      </p>
    </div>
  </footer>
</template>
