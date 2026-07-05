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
import { VERDICTS, WATCH_VERDICTS } from '@/utils/verdict'

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

const flagIs = (flag: string) => ['==', ['get', 'flag'], flag] as const
/** `attention` is absent on flagged features and the citywide payload —
 * coalesce keeps the comparison type-stable for maplibre. */
const attentionIs = (tier: string) =>
  ['==', ['coalesce', ['get', 'attention'], ''], tier] as const

/** Feature color: strong flags at full strength, the watch tier (within the
 * interval but near its edge) as tints of the same hues, everything else
 * quiet. */
export const flagColor = [
  'case',
  flagIs('over_assessed_candidate'), VERDICTS.over_assessed_candidate.hex,
  flagIs('under_assessed_candidate'), VERDICTS.under_assessed_candidate.hex,
  attentionIs('high'), WATCH_VERDICTS.high.hex,
  attentionIs('low'), WATCH_VERDICTS.low.hex,
  flagIs('within_range'), VERDICTS.within_range.hex,
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
 * Each entry carries the maplibre boolean expression selecting its dots, so
 * the legend doubles as a set of show/hide toggles; `tier` decides which dot
 * layer renders it (strong flags paint above watch, watch above the gray
 * base; only strong flags exist in the citywide low-zoom payload). */
export const legend = [
  {
    hex: VERDICTS.over_assessed_candidate.hex,
    label: 'Above our range',
    tier: 'strong',
    expr: flagIs('over_assessed_candidate'),
  },
  {
    hex: WATCH_VERDICTS.high.hex,
    label: 'Leaning high',
    tier: 'watch',
    expr: ['all', flagIs('within_range'), attentionIs('high')],
  },
  {
    hex: VERDICTS.within_range.hex,
    label: 'Inside our range',
    tier: 'base',
    expr: [
      'any',
      ['all', flagIs('within_range'), attentionIs('')],
      flagIs('no_assessment'),
    ],
  },
  {
    hex: WATCH_VERDICTS.low.hex,
    label: 'Leaning low',
    tier: 'watch',
    expr: ['all', flagIs('within_range'), attentionIs('low')],
  },
  {
    hex: VERDICTS.under_assessed_candidate.hex,
    label: 'Below our range',
    tier: 'strong',
    expr: flagIs('under_assessed_candidate'),
  },
] as const
