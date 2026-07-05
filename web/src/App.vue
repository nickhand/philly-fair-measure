<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { SITE } from '@/config/site'
import TaxYearBanner from '@/components/ui/TaxYearBanner.vue'
</script>

<template>
  <a class="skip-link" href="#main">Skip to main content</a>

  <!-- flag-gold rule: the one place gold touches the chrome -->
  <div class="h-1 bg-gold" aria-hidden="true"></div>

  <TaxYearBanner />

  <header class="border-b border-line bg-white">
    <nav
      class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3"
      aria-label="Main"
    >
      <RouterLink to="/" class="flex items-center gap-2.5" aria-label="Fair Measure — home">
        <svg width="26" height="17" viewBox="0 0 26 17" aria-hidden="true">
          <rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" />
          <rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" />
          <circle cx="21" cy="3" r="2.6" fill="#f3c613" />
        </svg>
        <!-- mark-only on small phones so four nav links fit -->
        <span class="hidden flex-col leading-none min-[480px]:flex">
          <span class="text-base font-extrabold tracking-tight text-ink">Fair Measure</span>
          <span class="mt-0.5 text-[9.5px] font-semibold uppercase tracking-[0.09em] text-muted">Philadelphia</span>
        </span>
      </RouterLink>
      <div class="flex items-center gap-0.5 text-body-sm font-semibold sm:gap-1.5">
        <RouterLink
          to="/map"
          class="rounded-sm px-2 py-2 text-[#334155] hover:bg-brand-50 sm:px-3"
          active-class="bg-brand-50 text-brand-600"
          >Map</RouterLink
        >
        <RouterLink
          to="/findings"
          class="rounded-sm px-2 py-2 text-[#334155] hover:bg-brand-50 sm:px-3"
          active-class="bg-brand-50 text-brand-600"
          >Findings</RouterLink
        >
        <RouterLink
          to="/methodology"
          class="rounded-sm px-2 py-2 text-[#334155] hover:bg-brand-50 sm:px-3"
          active-class="bg-brand-50 text-brand-600"
          >Methods</RouterLink
        >
        <RouterLink
          to="/trust"
          class="rounded-sm px-2 py-2 text-[#334155] hover:bg-brand-50 sm:px-3"
          active-class="bg-brand-50 text-brand-600"
          >The Proof</RouterLink
        >
      </div>
    </nav>
  </header>

  <main id="main" class="min-h-[70vh]">
    <RouterView />
  </main>

  <footer class="mt-12 border-t border-line bg-white">
    <div class="mx-auto max-w-5xl px-4 py-7">
      <!-- about: one paragraph, not five stacked lines -->
      <div class="flex items-start gap-2.5">
        <svg width="22" height="14" viewBox="0 0 26 17" aria-hidden="true" class="mt-1 shrink-0">
          <rect x="1" y="6" width="24" height="7" rx="3.5" fill="#b9d2ee" />
          <rect x="11" y="2" width="3.5" height="15" rx="1.2" fill="#0f4d90" />
          <circle cx="21" cy="3" r="2.6" fill="#f3c613" />
        </svg>
        <p class="max-w-3xl text-body-sm leading-relaxed text-muted">
          <strong class="text-ink">Fair Measure</strong> is a free, independent tool built only
          from the City of Philadelphia’s own open data — it is not run by the city. Our estimates
          are not appraisals, and nothing here is legal or tax advice; before you act, check the
          city’s records at
          <a
            href="https://property.phila.gov"
            class="font-semibold text-brand-600 underline"
            rel="noopener"
            >property.phila.gov</a
          >.
        </p>
      </div>

      <!-- link row -->
      <nav
        aria-label="Footer"
        class="mt-4 flex flex-wrap justify-center gap-x-5 gap-y-2 text-body-sm font-semibold"
      >
        <RouterLink to="/findings" class="text-brand-600 underline">What we found</RouterLink>
        <RouterLink to="/methodology" class="text-brand-600 underline">How it works</RouterLink>
        <RouterLink to="/trust" class="text-brand-600 underline">Why trust these numbers</RouterLink>
        <a :href="SITE.githubUrl" rel="noopener" class="text-brand-600 underline">Code &amp; data pipeline</a>
        <a :href="SITE.modelDocsUrl" rel="noopener" class="text-brand-600 underline">Model documentation</a>
      </nav>

      <!-- fine print -->
      <p class="mt-4 border-t border-line-faint pt-3 text-center text-caption text-faint">
        Designed and built by
        <a :href="SITE.creatorUrl" rel="noopener" class="font-semibold text-brand-600 underline"
          >{{ SITE.creatorName }}</a
        >
        · No ads, no cookies — anonymous usage statistics only · Independent, not a City of
        Philadelphia product
      </p>
    </div>
  </footer>
</template>
