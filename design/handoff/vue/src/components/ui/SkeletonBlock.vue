<script setup lang="ts">
/** SkeletonBlock — loading placeholder whose shapes echo the verdict card,
 * so nothing jumps on load. `.skeleton` (shimmer + reduced-motion static)
 * is defined in main.css. */
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-line-soft bg-white" role="status" aria-label="Loading">
    <div class="h-1.5 bg-[#e4e9f0]"></div>
    <div class="flex flex-col gap-3 p-4">
      <div class="flex items-center gap-3">
        <div class="skeleton h-10 w-10 rounded-full"></div>
        <div class="flex flex-1 flex-col gap-2">
          <div class="skeleton h-4 w-3/4"></div>
          <div class="skeleton h-3 w-2/5"></div>
        </div>
      </div>
      <div class="skeleton h-3 w-full"></div>
      <div class="skeleton h-3 w-11/12"></div>
      <div class="relative mt-1 h-14 rounded-md bg-[#edf1f6]">
        <div class="skeleton absolute left-[12%] right-[38%] top-4 h-5"></div>
      </div>
    </div>
    <span class="sr-only">Loading…</span>
  </div>
</template>
