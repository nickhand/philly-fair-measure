<script setup lang="ts">
/** Compact, directly labeled boundary comparison for the annual report. */
import { computed } from 'vue'

type TransectSummary = {
  label: string
  n: number
  median_change_pct: number
  corrective_pct: number
  widening_pct: number
}

type TransectBand = TransectSummary & {
  distance_min_m: number
  distance_max_m: number | null
}

type BoundaryTransect = {
  core_label: string
  corridor_label: string
  core: TransectSummary
  bands: TransectBand[]
}

const props = defineProps<{ transect: BoundaryTransect }>()

type PlotPoint = TransectSummary & { axisLabel: string; areaLabel: string }

const points = computed<PlotPoint[]>(() => [
  {
    ...props.transect.core,
    axisLabel: 'Core side',
    areaLabel: props.transect.core_label,
  },
  ...props.transect.bands.map((band) => ({
    ...band,
    axisLabel: band.label,
    areaLabel: props.transect.corridor_label,
  })),
])

const chartMax = computed(() => {
  const peak = Math.max(
    ...points.value.flatMap((point) => [point.widening_pct, point.corrective_pct]),
  )
  return Math.max(80, Math.ceil(peak / 10) * 10)
})

function barWidth(value: number): string {
  return `${Math.min(100, (value / chartMax.value) * 100)}%`
}

function signedPct(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${Math.abs(value).toFixed(1)}%`
}
</script>

<template>
  <figure
    role="img"
    :aria-label="`Across the boundary, ${transect.core.corrective_pct}% of reliable records on the core side got better by moving closer to the benchmark. In the first half-kilometer on the Kensington side, ${transect.bands[0]?.widening_pct}% got worse by moving farther away.`"
  >
    <figcaption class="mb-3 text-caption leading-relaxed text-muted">
      Share of reliable properties. Better means closer to our estimate; worse means farther away.
      Bars use the same 0–{{ chartMax }}% scale.
    </figcaption>

    <div class="transect-grid transect-head" aria-hidden="true">
      <span>Area</span>
      <span class="farther-label">Worse: farther</span>
      <span class="closer-label">Better: closer</span>
      <span class="text-right">Assessment change</span>
    </div>

    <div
      v-for="(point, index) in points"
      :key="`${point.axisLabel}-${index}`"
      class="transect-grid transect-row"
      :class="{ 'boundary-start': index === 1 }"
    >
      <div class="min-w-0">
        <p class="area-name">{{ point.axisLabel }}</p>
        <p class="area-side">{{ point.areaLabel }}</p>
      </div>

      <div class="measure farther-measure">
        <span class="measure-value">{{ point.widening_pct.toFixed(1) }}%</span>
        <span class="track" aria-hidden="true">
          <span class="farther-bar" :style="{ width: barWidth(point.widening_pct) }"></span>
        </span>
      </div>

      <div class="measure closer-measure">
        <span class="measure-value">{{ point.corrective_pct.toFixed(1) }}%</span>
        <span class="track" aria-hidden="true">
          <span class="closer-bar" :style="{ width: barWidth(point.corrective_pct) }"></span>
        </span>
      </div>

      <p class="money change-value">{{ signedPct(point.median_change_pct) }}</p>
    </div>
  </figure>
</template>

<style scoped>
.transect-grid {
  display: grid;
  grid-template-columns: minmax(92px, 1.2fr) minmax(72px, 1fr) minmax(72px, 1fr) minmax(68px, 0.8fr);
  column-gap: 16px;
  align-items: center;
}

.transect-head {
  padding: 0 0 8px;
  border-bottom: 1px solid var(--color-line);
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 500;
}

.transect-row {
  min-height: 64px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-line-faint);
}

.boundary-start {
  margin-top: 8px;
  border-top: 2px solid var(--color-gold-700);
}

.area-name,
.measure-value,
.change-value {
  color: var(--color-ink);
  font-size: 13px;
  font-weight: 500;
}

.area-side {
  margin-top: 2px;
  overflow: hidden;
  color: var(--color-muted);
  font-size: 11px;
  line-height: 1.25;
  text-overflow: ellipsis;
}

.farther-label::before,
.closer-label::before {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  content: '';
}

.farther-label::before {
  background: var(--color-over);
}

.closer-label::before {
  border-radius: 999px;
  background: var(--color-brand-600);
}

.measure {
  min-width: 0;
}

.measure-value {
  display: block;
  font-variant-numeric: tabular-nums;
}

.track {
  display: block;
  height: 3px;
  margin-top: 5px;
  background: var(--color-line-faint);
}

.farther-bar,
.closer-bar {
  display: block;
  height: 100%;
}

.farther-bar {
  background: var(--color-over);
}

.closer-bar {
  background: var(--color-brand-600);
}

.change-value {
  text-align: right;
}

@media (max-width: 520px) {
  .transect-grid {
    grid-template-columns: minmax(76px, 1.1fr) minmax(62px, 0.9fr) minmax(62px, 0.9fr) minmax(54px, 0.7fr);
    column-gap: 8px;
  }

  .transect-head,
  .area-name,
  .measure-value,
  .change-value {
    font-size: 11px;
  }

  .transect-head {
    line-height: 1.2;
  }

  .transect-row {
    min-height: 58px;
    padding: 8px 0;
  }

  .area-side {
    display: none;
  }
}
</style>
