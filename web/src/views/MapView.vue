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
import type { PropertyCore, SearchHit } from '@/api/types'
import { applyFairMeasurePaint, dotLayers, legend } from '@/map/fairMeasureMapStyle'
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
    for (const layer of dotLayers('parcels')) m.addLayer({ ...layer, minzoom: MIN_PARCEL_ZOOM })
    m.on('click', 'fm-dots', (e) => {
      const id = e.features?.[0]?.properties?.id as string | undefined
      if (id) openParcel(id)
    })
    m.on('mouseenter', 'fm-dots', () => (m.getCanvas().style.cursor = 'pointer'))
    m.on('mouseleave', 'fm-dots', () => (m.getCanvas().style.cursor = ''))
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

    <div
      ref="container"
      class="absolute inset-0"
      role="region"
      aria-label="Map of Philadelphia homes colored by assessment check result. Use the address search above the map if you prefer not to use the map."
    ></div>

    <!-- floating search -->
    <div class="absolute inset-x-3 top-3 z-10 mx-auto max-w-[560px]">
      <AddressSearch compact @select="onSearchSelect" />
    </div>

    <!-- legend: part of the map furniture, not a boxed panel -->
    <div
      class="absolute left-3 top-[66px] z-10 flex max-w-[300px] flex-wrap gap-1.5"
      role="list"
      aria-label="Map legend"
    >
      <span
        v-for="l in legend"
        :key="l.label"
        role="listitem"
        class="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1.5 text-[11.5px] font-semibold text-body shadow-float"
      >
        <span class="h-2 w-2 rounded-full" :style="{ background: l.hex }" aria-hidden="true"></span>
        {{ l.label }}
      </span>
    </div>

    <!-- zoom hint -->
    <div
      v-if="zoomedOut"
      class="pointer-events-none absolute left-1/2 top-[118px] z-10 -translate-x-1/2 rounded-full bg-[rgba(22,36,58,0.85)] px-3.5 py-1.5 text-[11.5px] font-semibold text-white"
      role="status"
    >
      Zoom in to see individual homes
    </div>
    <div
      v-if="loadError"
      class="absolute inset-x-0 bottom-24 z-10 mx-auto w-fit rounded-full bg-over px-4 py-2 text-sm font-semibold text-white"
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
