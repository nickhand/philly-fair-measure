<script setup lang="ts">
/** Citywide map. Homes appear as verdict-colored dots at street zoom (the API
 * serves the current viewport; a PMTiles vector layer is the drop-in
 * replacement for static deploys — see docs/frontend.md).
 *
 * Handoff design (fairMeasureMapStyle paint overrides, dot layers + selected
 * highlight, legend chips) merged onto our tested wiring: layer setup is
 * `styledata`-based and idempotent (`load` never fires in some embedded
 * browsers and stalls on slow glyph CDNs), and `moveend` refreshes the
 * viewport parcels independent of style readiness. The address search is the
 * accessible alternative to map interaction. */
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '@/api/client'
import { track } from '@/lib/analytics'
import type { PropertyCore, SearchHit } from '@/api/types'
import { applyFairMeasurePaint, dotLayers, flagColor, legend } from '@/map/fairMeasureMapStyle'
import AddressSearch from '@/components/search/AddressSearch.vue'
import PropertySheet from '@/components/map/PropertySheet.vue'

const MIN_PARCEL_ZOOM = 14.5
const PHILLY_CENTER: [number, number] = [-75.16, 39.985]

const router = useRouter()
const container = ref<HTMLDivElement | null>(null)
/** Which legend groups are visible; chips toggle these on/off. */
const enabledLabels = ref<Set<string>>(new Set(legend.map((l) => l.label)))
/** Condo flags come from the condo-unit model and cluster in Center City
 * towers — a separate toggle (applied at every zoom) keeps them from being
 * read as the rowhome pattern. */
const showCondos = ref(true)

/** OR the enabled legend chips of the given tiers into one layer filter;
 * an all-off selection matches nothing. */
function tierFilter(tiers: readonly string[]): maplibregl.FilterSpecification {
  const exprs = legend
    .filter((l) => tiers.includes(l.tier) && enabledLabels.value.has(l.label))
    .map((l) => l.expr as unknown)
  const combined = exprs.length ? ['any', ...exprs] : ['==', ['get', 'flag'], '__none__']
  return (
    showCondos.value ? combined : ['all', combined, ['!=', ['get', 'family'], 'condo']]
  ) as maplibregl.FilterSpecification
}

function applyDotFilter() {
  const m = map.value
  if (!m) return
  if (m.getLayer('fm-dots-base')) m.setFilter('fm-dots-base', tierFilter(['base']))
  // watch tints share the top layer so they paint above the gray majority
  if (m.getLayer('fm-dots-flagged')) m.setFilter('fm-dots-flagged', tierFilter(['strong', 'watch']))
  // citywide: watch texture below, strong flags on top
  if (m.getLayer('fm-dots-far')) m.setFilter('fm-dots-far', tierFilter(['strong']))
  if (m.getLayer('fm-dots-far-watch')) m.setFilter('fm-dots-far-watch', tierFilter(['watch']))
}

function toggleCondos() {
  showCondos.value = !showCondos.value
  track('map_filter_toggled', { group: 'condos', on: showCondos.value })
  applyDotFilter()
}

function toggleLegend(label: string) {
  const next = new Set(enabledLabels.value)
  if (next.has(label)) next.delete(label)
  else next.add(label)
  enabledLabels.value = next
  track('map_filter_toggled', { group: label, on: next.has(label) })
  applyDotFilter()
}
const map = shallowRef<maplibregl.Map | null>(null)
const selected = ref<PropertyCore | null>(null)
const zoomedOut = ref(true)
const loadError = ref(false)

let controller: AbortController | undefined
let painted = false

async function refreshParcels() {
  const m = map.value
  if (!m) return
  zoomedOut.value = m.getZoom() < MIN_PARCEL_ZOOM
  const source = m.getSource('parcels') as maplibregl.GeoJSONSource | undefined
  if (!source) return
  if (zoomedOut.value) {
    source.setData({ type: 'FeatureCollection', features: [] })
    return
  }
  controller?.abort()
  controller = new AbortController()
  const b = m.getBounds()
  try {
    const fc = await api.parcels(
      [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()],
      controller.signal,
    )
    source.setData(fc)
  } catch (err) {
    if ((err as Error).name !== 'AbortError') loadError.value = true
  }
}

async function openParcel(parcelId: string) {
  track('map_parcel_opened')
  try {
    selected.value = await api.property(parcelId)
    map.value?.setFilter('fm-dot-selected', ['==', ['get', 'id'], parcelId])
  } catch {
    selected.value = null
  }
}

function closeSheet() {
  selected.value = null
  map.value?.setFilter('fm-dot-selected', ['==', ['get', 'id'], ''])
}

async function onSearchSelect(hit: SearchHit) {
  await openParcel(hit.parcel_id)
  const p = selected.value
  if (p?.lon != null && p.lat != null) {
    map.value?.flyTo({ center: [p.lon, p.lat], zoom: 17 })
  } else {
    router.push({ name: 'property', params: { parcelId: hit.parcel_id } })
  }
}

/** Add paint overrides + the parcel source/layers as soon as the style can
 * accept them. Deliberately NOT gated on the `load` event; `styledata` fires
 * early and repeatedly, and this wiring is idempotent. */
function ensureParcelLayer(m: maplibregl.Map) {
  if (!painted && m.isStyleLoaded()) {
    applyFairMeasurePaint(m)
    painted = true
  }
  if (m.getSource('parcels')) return
  try {
    m.addSource('parcels', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    // Near layers: within-range dots first, flagged dots after (flagged homes
    // always paint ON TOP of the gray majority), then the selected ring.
    const [dotsSpec, selectedSpec] = dotLayers('parcels')
    m.addLayer({ ...dotsSpec!, id: 'fm-dots-base', minzoom: MIN_PARCEL_ZOOM })
    m.addLayer({ ...dotsSpec!, id: 'fm-dots-flagged', minzoom: MIN_PARCEL_ZOOM })
    m.addLayer({ ...selectedSpec!, minzoom: MIN_PARCEL_ZOOM })
    // Citywide pattern layers: every flagged + watch-tier home (~51k points,
    // one cached gzipped payload) drawn below street zoom so the clustering
    // reads at a glance; the viewport layer takes over past MIN_PARCEL_ZOOM.
    // Watch dots render first as a small faint texture, strong flags on top.
    m.addSource('flagged', { type: 'geojson', data: '/api/parcels/flagged' })
    m.addLayer({
      id: 'fm-dots-far-watch',
      type: 'circle',
      source: 'flagged',
      maxzoom: MIN_PARCEL_ZOOM,
      paint: {
        'circle-color': flagColor as unknown as string,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 1.4, 13, 2.4, 14.5, 3.4],
        'circle-opacity': 0.55,
      },
    })
    m.addLayer({
      id: 'fm-dots-far',
      type: 'circle',
      source: 'flagged',
      maxzoom: MIN_PARCEL_ZOOM,
      paint: {
        'circle-color': flagColor as unknown as string,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2.2, 13, 3.4, 14.5, 4.5],
        'circle-opacity': 0.9,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 0.4, 13, 1],
      },
    })
    applyDotFilter()
    for (const layerId of ['fm-dots-base', 'fm-dots-flagged', 'fm-dots-far', 'fm-dots-far-watch']) {
      m.on('click', layerId, (e) => {
        const id = e.features?.[0]?.properties?.id as string | undefined
        if (id) openParcel(id)
      })
      m.on('mouseenter', layerId, () => (m.getCanvas().style.cursor = 'pointer'))
      m.on('mouseleave', layerId, () => (m.getCanvas().style.cursor = ''))
    }
    refreshParcels()
  } catch {
    // style not ready for layers yet — the next styledata event retries
  }
}

onMounted(() => {
  if (!container.value) return
  const m = new maplibregl.Map({
    container: container.value,
    style: 'https://tiles.openfreemap.org/styles/positron',
    center: PHILLY_CENTER,
    zoom: 11.4,
    attributionControl: { compact: true },
  })
  // top-right so the bottom sheet never covers them on mobile
  m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  m.addControl(new maplibregl.GeolocateControl({}), 'top-right')

  m.on('styledata', () => ensureParcelLayer(m))
  m.on('moveend', refreshParcels) // independent of style readiness
  map.value = m
  if (import.meta.env.DEV) {
    // debugging handle for browser devtools; stripped from production builds
    ;(window as unknown as { __map?: maplibregl.Map }).__map = m
  }
})

onBeforeUnmount(() => {
  controller?.abort()
  map.value?.remove()
})
</script>

<template>
  <div class="relative h-[calc(100dvh-118px)] min-h-[420px]">
    <h1 class="sr-only">Assessment map of Philadelphia</h1>

    <!-- Sized explicitly (h-full, not absolute inset-0): maplibre-gl.css loads
         after Tailwind in the lazy map chunk and its .maplibregl-map rule sets
         position: relative, which beats the .absolute utility and collapses an
         inset-positioned container to zero height. -->
    <div
      ref="container"
      class="h-full w-full"
      role="region"
      aria-label="Map of Philadelphia homes colored by assessment check result. Use the address search above the map if you prefer not to use the map."
    ></div>

    <!-- floating search -->
    <div class="absolute inset-x-3 top-3 z-10 mx-auto max-w-[560px]">
      <AddressSearch compact @select="onSearchSelect" />
    </div>

    <!-- legend chips double as show/hide toggles; a vertical column ordered
         high → low so it reads like the scale it encodes -->
    <div
      class="absolute left-3 top-[66px] z-10 flex w-fit flex-col items-stretch gap-1.5"
      role="group"
      aria-label="Show or hide homes by result"
    >
      <span
        aria-hidden="true"
        class="w-fit rounded-full bg-[rgba(22,36,58,0.72)] px-2 py-0.5 text-caption font-bold text-white"
        >Show:</span
      >
      <button
        v-for="l in legend"
        :key="l.label"
        type="button"
        :aria-pressed="enabledLabels.has(l.label)"
        class="inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 py-1.5 text-caption font-semibold shadow-float transition-colors duration-[var(--duration-fast)]"
        :class="
          enabledLabels.has(l.label)
            ? 'border-line-soft bg-white text-body'
            : 'border-line bg-paper text-faint line-through'
        "
        @click="toggleLegend(l.label)"
      >
        <span
          class="h-2.5 w-2.5 rounded-full"
          :style="{ background: enabledLabels.has(l.label) ? l.hex : '#c3ccd6' }"
          aria-hidden="true"
        ></span>
        {{ l.label }}
      </button>
      <button
        type="button"
        :aria-pressed="showCondos"
        class="inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 py-1.5 text-caption font-semibold shadow-float transition-colors duration-[var(--duration-fast)]"
        :class="showCondos ? 'border-line-soft bg-white text-body' : 'border-line bg-paper text-muted'"
        @click="toggleCondos"
      >
        <!-- explicit checkbox glyph: this chip is a filter, not a legend entry -->
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" :stroke="showCondos ? '#0f4d90' : '#8593a4'" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
          <path v-if="showCondos" d="M8 12.5 11 15.5 16.5 9" />
        </svg>
        Condos
      </button>
    </div>

    <!-- zoom hint -->
    <div
      v-if="zoomedOut"
      class="pointer-events-none absolute left-1/2 top-[118px] z-10 w-max max-w-[92vw] -translate-x-1/2 rounded-full bg-[rgba(22,36,58,0.85)] px-3.5 py-1.5 text-center text-caption font-semibold text-white"
      role="status"
    >
      Showing flagged homes and ones worth a look citywide — zoom in to see every home
    </div>
    <div
      v-if="loadError"
      class="absolute inset-x-0 bottom-24 z-10 mx-auto w-fit rounded-full bg-over px-4 py-2 text-body-sm font-semibold text-white"
      role="alert"
    >
      Could not load homes for this area. Pan or zoom to retry.
    </div>

    <!-- bottom sheet -->
    <div v-if="selected" class="absolute inset-x-0 bottom-0 z-20 mx-auto max-w-[560px]">
      <PropertySheet :property="selected" @close="closeSheet" />
    </div>
  </div>
</template>

<style scoped>
/* Keep the map's own controls clear of the floating search bar. */
:deep(.maplibregl-ctrl-top-right) {
  top: 4.25rem;
}
</style>
