/** Small typed fetch layer. All endpoints are same-origin `/api/*` (vite proxies
 * to the Python API in dev). Callers pass an AbortSignal to cancel stale
 * requests (the address search does this on every keystroke). */

import type {
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

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } })
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

  parcels: (bbox: [number, number, number, number], signal?: AbortSignal) =>
    get<ParcelCollection>(
      `/api/parcels?minx=${bbox[0]}&miny=${bbox[1]}&maxx=${bbox[2]}&maxy=${bbox[3]}`,
      signal,
    ),

  leaderboard: (kind: 'over' | 'under' | 'nonuniform', n = 25, signal?: AbortSignal) =>
    get<LeaderRow[]>(`/api/admin/leaderboard?kind=${kind}&n=${n}`, signal),
}
