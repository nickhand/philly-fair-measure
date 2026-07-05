<script setup lang="ts">
/** Citywide map. Homes appear as dots colored by verdict once you zoom to
 * street level (the API serves the current viewport; a PMTiles vector layer
 * is the drop-in replacement for static deploys — see docs/frontend.md).
 * The address search is the accessible alternative to map interaction. */
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '@/api/client'
import type { PropertyCore, SearchHit } from '@/api/types'
import { VERDICTS } from '@/utils/verdict'
import AddressSearch from '@/components/search/AddressSearch.vue'
import PropertySheet from '@/components/map/PropertySheet.vue'

const MIN_PARCEL_ZOOM = 14.5
const PHILLY_CENTER: [number, number] = [-75.16, 39.985]

const router = useRouter()
const container = ref<HTMLDivElement | null>(null)
const map = shallowRef<maplibregl.Map | null>(null)
const selected = ref<PropertyCore | null>(null)
const zoomedOut = ref(true)
const loadError = ref(false)

let controller: AbortController | undefined

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
  try {
    selected.value = await api.property(parcelId)
  } catch {
    selected.value = null
  }
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

/** Add the parcel source/layer as soon as the style can accept them.
 * Deliberately NOT gated on the `load` event: `load` waits for every glyph
 * and sprite, which can stall on slow CDNs (and never fires in some embedded
 * browsers). `styledata` fires early and repeatedly; wiring is idempotent. */
function ensureParcelLayer(m: maplibregl.Map) {
  if (m.getSource('parcels')) return
  try {
    m.addSource('parcels', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    m.addLayer({
      id: 'parcel-dots',
      type: 'circle',
      source: 'parcels',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 14.5, 3.5, 18, 9],
        'circle-color': [
          'match',
          ['get', 'flag'],
          'over_assessed_candidate',
          VERDICTS.over_assessed_candidate.hex,
          'under_assessed_candidate',
          VERDICTS.under_assessed_candidate.hex,
          /* within/other */ '#94a3b8',
        ],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#ffffff',
      },
    })
    m.on('click', 'parcel-dots', (e) => {
      const id = e.features?.[0]?.properties?.id as string | undefined
      if (id) openParcel(id)
    })
    m.on('mouseenter', 'parcel-dots', () => (m.getCanvas().style.cursor = 'pointer'))
    m.on('mouseleave', 'parcel-dots', () => (m.getCanvas().style.cursor = ''))
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
  <div class="relative h-[calc(100vh-8rem)] min-h-[480px]">
    <h1 class="sr-only">Assessment map of Philadelphia</h1>

    <!-- search overlay -->
    <div class="absolute inset-x-0 top-3 z-20 mx-auto w-[min(92%,28rem)]">
      <AddressSearch compact @select="onSearchSelect" />
    </div>

    <div
      ref="container"
      class="h-full w-full"
      role="region"
      aria-label="Map of Philadelphia homes colored by assessment check result. Use the address search above the map if you prefer not to use the map."
    ></div>

    <!-- zoom hint -->
    <div
      v-if="zoomedOut"
      class="pointer-events-none absolute inset-x-0 bottom-24 z-10 mx-auto w-fit rounded-full bg-slate-900/80 px-4 py-2 text-sm font-medium text-white"
      role="status"
    >
      Zoom in to street level to see homes
    </div>
    <div
      v-if="loadError"
      class="absolute inset-x-0 bottom-24 z-10 mx-auto w-fit rounded-full bg-over px-4 py-2 text-sm font-medium text-white"
      role="alert"
    >
      Could not load homes for this area. Pan or zoom to retry.
    </div>

    <!-- legend -->
    <div
      class="absolute top-20 left-3 z-10 rounded-xl border border-slate-200 bg-white/95 p-3 text-xs shadow sm:top-auto sm:bottom-8"
      role="img"
      aria-label="Legend: orange means the city value is above our range, blue means below, gray means it looks fair."
    >
      <p class="mb-1.5 font-bold text-slate-800">City value vs our range</p>
      <ul class="space-y-1" aria-hidden="true">
        <li class="flex items-center gap-2">
          <span class="h-3 w-3 rounded-full" style="background: #c2410c"></span> Above (may be high)
        </li>
        <li class="flex items-center gap-2">
          <span class="h-3 w-3 rounded-full" style="background: #1d4ed8"></span> Below
        </li>
        <li class="flex items-center gap-2">
          <span class="h-3 w-3 rounded-full bg-slate-400"></span> Looks fair
        </li>
      </ul>
    </div>

    <PropertySheet v-if="selected" :property="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
/* Keep the map's own controls clear of the floating search bar. */
:deep(.maplibregl-ctrl-top-right) {
  top: 4.25rem;
}
</style>
