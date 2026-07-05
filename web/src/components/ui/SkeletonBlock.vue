<template>
  <!-- shapes echo the verdict-card anatomy: bar, icon circle, two lines, band -->
  <div class="space-y-3" role="status" aria-label="Loading">
    <div class="skeleton h-1.5 w-full"></div>
    <div class="flex items-center gap-3">
      <div class="skeleton h-10 w-10 rounded-full!"></div>
      <div class="skeleton h-5 w-2/5"></div>
    </div>
    <div class="skeleton h-3.5 w-4/5"></div>
    <div class="skeleton h-3.5 w-3/5"></div>
    <div class="skeleton h-16 w-full rounded-lg!"></div>
    <span class="sr-only">Loading…</span>
  </div>
</template>
