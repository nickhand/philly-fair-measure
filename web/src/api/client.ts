/** Small typed fetch layer. Endpoints are `/api/*` — same-origin in dev (vite
 * proxies to the Python API), prefixed with VITE_API_BASE in production
 * builds (the Netlify site calls the Fly.io API cross-origin). Callers pass
 * an AbortSignal to cancel stale requests (the address search does this on
 * every keystroke). */

import type {
  CompRow,
  LeaderRow,
  ParcelCollection,
  PropertyCore,
  Report,
  SearchHit,
  Stats,
} from './types'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Absolute URL for an /api path (also used for non-fetch consumers like the
 * map's GeoJSON source). Empty base = same origin. */
export function apiUrl(path: string): string {
  return `${import.meta.env.VITE_API_BASE ?? ''}${path}`
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(apiUrl(path), { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) throw new ApiError(res.status, `${res.status} for ${path}`)
  return (await res.json()) as T
}

export const api = {
  stats: (signal?: AbortSignal) => get<Stats>('/api/stats', signal),

  search: (q: string, signal?: AbortSignal) =>
    get<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}`, signal),

  property: (parcelId: string, signal?: AbortSignal) =>
    get<PropertyCore>(`/api/property/${encodeURIComponent(parcelId)}`, signal),

  report: (parcelId: string, signal?: AbortSignal) =>
    get<Report>(`/api/property/${encodeURIComponent(parcelId)}/report`, signal),

  /** Slow (~seconds — the model recomputes leaf-node comps); load on demand. */
  comps: (parcelId: string, signal?: AbortSignal) =>
    get<CompRow[]>(`/api/property/${encodeURIComponent(parcelId)}/comps`, signal),

  parcels: (bbox: [number, number, number, number], signal?: AbortSignal) =>
    get<ParcelCollection>(
      `/api/parcels?minx=${bbox[0]}&miny=${bbox[1]}&maxx=${bbox[2]}&maxy=${bbox[3]}`,
      signal,
    ),

  leaderboard: (kind: 'over' | 'under' | 'nonuniform', n = 25, signal?: AbortSignal) =>
    get<LeaderRow[]>(`/api/admin/leaderboard?kind=${kind}&n=${n}`, signal),
}
