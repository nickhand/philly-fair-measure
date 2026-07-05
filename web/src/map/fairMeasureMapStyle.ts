/** Fair Measure map styling — applied on top of the CARTO Positron style.
 *
 * Two jobs:
 *  1. applyFairMeasurePaint(map): recolor the basemap to the design's quiet
 *     paper palette (land #eef0f1, water #ccd8e2, roads white, parks #dce8dc,
 *     labels muted) without replacing the style — zero perf cost.
 *  2. dotLayers(): the parcel-dot layers, colored by verdict flag with the
 *     hexes from utils/verdict.ts (single source of truth).
 *
 * Verified against our /api/parcels GeoJSON: feature properties are
 * `flag` (as assumed) and `id` (not `parcel_id`) — the selected-dot filter
 * below uses `id`.
 */
import type { Map as MLMap, LayerSpecification } from 'maplibre-gl'
import { VERDICTS } from '@/utils/verdict'

const LAND = '#eef0f1'
const WATER = '#ccd8e2'
const ROAD = '#ffffff'
const PARK = '#dce8dc'
const LABEL = '#8593a4'
const LABEL_HALO = '#ffffff'

export function applyFairMeasurePaint(map: MLMap): void {
  for (const layer of map.getStyle().layers ?? []) {
    const id = layer.id
    try {
      if (layer.type === 'background') {
        map.setPaintProperty(id, 'background-color', LAND)
      } else if (layer.type === 'fill') {
        if (/water|ocean|river/.test(id)) map.setPaintProperty(id, 'fill-color', WATER)
        else if (/park|green|wood|grass|cemetery/.test(id)) map.setPaintProperty(id, 'fill-color', PARK)
        else if (/land|earth|residential|building/.test(id)) map.setPaintProperty(id, 'fill-color', LAND)
      } else if (layer.type === 'line' && /road|street|highway|bridge|tunnel|path/.test(id)) {
        map.setPaintProperty(id, 'line-color', ROAD)
      } else if (layer.type === 'symbol') {
        map.setPaintProperty(id, 'text-color', LABEL)
        map.setPaintProperty(id, 'text-halo-color', LABEL_HALO)
      }
    } catch {
      /* some layers lack the property — fine */
    }
  }
}

/** Match expression: feature.flag → verdict hex. */
export const flagColor = [
  'match',
  ['get', 'flag'],
  'over_assessed_candidate', VERDICTS.over_assessed_candidate.hex,
  'under_assessed_candidate', VERDICTS.under_assessed_candidate.hex,
  'within_range', VERDICTS.within_range.hex,
  VERDICTS.no_assessment.hex,
] as const

/** Dot layers: base dots + a white-ring highlight for the selected parcel. */
export function dotLayers(sourceId: string, sourceLayer?: string): LayerSpecification[] {
  const common = sourceLayer ? { source: sourceId, 'source-layer': sourceLayer } : { source: sourceId }
  return [
    {
      id: 'fm-dots',
      type: 'circle',
      ...common,
      paint: {
        'circle-color': flagColor as unknown as string,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 15, 4.5, 17, 6],
        'circle-opacity': 0.92,
      },
    },
    {
      id: 'fm-dot-selected',
      type: 'circle',
      ...common,
      filter: ['==', ['get', 'id'], ''],
      paint: {
        'circle-color': flagColor as unknown as string,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 5, 17, 9],
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 3,
      },
    },
  ] as LayerSpecification[]
}

/** Legend entries — short semantic labels (headlines are too long for chips).
 * `flags` lists the feature-flag values each chip controls, so the legend can
 * double as a set of show/hide toggles. */
export const legend = [
  {
    hex: VERDICTS.over_assessed_candidate.hex,
    label: 'Above our range',
    flags: ['over_assessed_candidate'],
  },
  {
    hex: VERDICTS.within_range.hex,
    label: 'Inside',
    flags: ['within_range', 'no_assessment'],
  },
  {
    hex: VERDICTS.under_assessed_candidate.hex,
    label: 'Below',
    flags: ['under_assessed_candidate'],
  },
] as const
