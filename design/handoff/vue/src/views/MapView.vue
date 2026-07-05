<script setup lang="ts">
/** Map — full-bleed restyled Positron, verdict-colored dots, floating search,
 * legend chips, zoom hint, bottom sheet.
 * Verify against your existing MapView: the dot source (assumed a GeoJSON or
 * vector-tile source of parcel points with `flag` + `parcel_id` properties)
 * and how the selected parcel's core is fetched (assumed api.property). */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '@/api/client'
import type { PropertyCore } from '@/api/types'
import AddressSearch from '@/components/search/AddressSearch.vue'
import PropertySheet from '@/components/map/PropertySheet.vue'
import { applyFairMeasurePaint, dotLayers, legend } from '@/map/fairMeasureMapStyle'

const container = ref<HTMLDivElement | null>(null)
const selected = ref<PropertyCore | null>(null)
const showZoomHint = ref(true)
let map: maplibregl.Map | undefined

const DOTS_MIN_ZOOM = 15

onMounted(() => {
  map = new maplibregl.Map({
    container: container.value!,
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: [-75.15, 39.965],
    zoom: 12,
    attributionControl: { compact: true },
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')

  map.on('load', () => {
    applyFairMeasurePaint(map!)
    // VERIFY: replace with your real parcel-points source.
    map!.addSource('parcels', { type: 'geojson', data: '/api/map/parcels.geojson' })
    for (const layer of dotLayers('parcels')) map!.addLayer({ ...layer, minzoom: DOTS_MIN_ZOOM })

    map!.on('click', 'fm-dots', async (e) => {
      const id = e.features?.[0]?.properties?.parcel_id
      if (!id) return
      map!.setFilter('fm-dot-selected', ['==', ['get', 'parcel_id'], id])
      try {
        selected.value = await api.property(id)
      } catch {
        selected.value = null
      }
    })
    map!.on('mouseenter', 'fm-dots', () => (map!.getCanvas().style.cursor = 'pointer'))
    map!.on('mouseleave', 'fm-dots', () => (map!.getCanvas().style.cursor = ''))
  })
  map.on('zoom', () => {
    showZoomHint.value = (map?.getZoom() ?? 0) < DOTS_MIN_ZOOM
  })
})
onBeforeUnmount(() => map?.remove())

function closeSheet() {
  selected.value = null
  map?.setFilter('fm-dot-selected', ['==', ['get', 'parcel_id'], ''])
}
</script>

<template>
  <div class="relative h-[calc(100dvh-118px)] min-h-[420px]">
    <div ref="container" class="absolute inset-0" aria-label="Map of Philadelphia property assessments"></div>

    <!-- floating search -->
    <div class="absolute left-3 right-3 top-3 z-10 mx-auto max-w-[560px]">
      <AddressSearch variant="float" placeholder="Search an address" />
    </div>

    <!-- legend: part of the map furniture, not a boxed panel -->
    <div class="absolute left-3 top-[66px] z-10 flex max-w-[300px] flex-wrap gap-1.5" role="list" aria-label="Map legend">
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
      v-if="showZoomHint"
      class="pointer-events-none absolute left-1/2 top-[118px] z-10 -translate-x-1/2 rounded-full bg-[rgba(22,36,58,0.85)] px-3.5 py-1.5 text-[11.5px] font-semibold text-white"
      role="status"
    >
      Zoom in to see individual homes
    </div>

    <!-- bottom sheet -->
    <div v-if="selected" class="absolute inset-x-0 bottom-0 z-20 mx-auto max-w-[560px]">
      <PropertySheet :core="selected" @close="closeSheet" />
    </div>
  </div>
</template>
