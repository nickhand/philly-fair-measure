/** Mirrors the pydantic response models in src/philly_assessments/api.py. */

export type Flag =
  | 'over_assessed_candidate'
  | 'under_assessed_candidate'
  | 'within_range'
  | 'no_assessment'

/** Within-range but in the outer part of the interval — "worth a closer
 * look", deliberately weaker language than a flag. */
export type Attention = 'high' | 'low' | null

export interface SearchHit {
  parcel_id: string
  address: string
  opa_market_value: number | null
}

export interface Signals {
  aerial_change: boolean
  aerial_pair: string | null
  vacancy_complaints_5y: number | null
  unpermitted_work_complaints_5y: number | null
  tax_delinquent: boolean
  rental_license: boolean
  linked_parcels: number | null
}

export interface PropertyCore {
  parcel_id: string
  address: string
  category: string | null
  model_family: string | null
  interval_method: string | null
  opa_market_value: number | null
  model_median: number | null
  model_pi_low_90: number | null
  model_pi_high_90: number | null
  ratio: number | null
  screen_z: number | null
  flag: Flag
  attention: Attention
  twin_n: number | null
  twin_ratio: number | null
  lon: number | null
  lat: number | null
  signals: Signals
}

export interface DriverOut {
  label: string
  group: string
  value: string | null
  dollars: number
}

export interface GroupEffect {
  group: string
  dollars: number
}

export interface AppealFact {
  label: string
  recorded: string
  dollars: number
  implausible: boolean
  /** The city has no value on file; the model substituted a typical value. */
  missing: boolean
}

export interface Drivers {
  base_value: number
  value: number
  drivers: DriverOut[]
  groups: GroupEffect[]
  sentences: string[]
  appeal_facts: AppealFact[]
}

export interface HistBin {
  x0: number
  x1: number
  n: number
}

export interface Equity {
  ratio: number
  peer_median_ratio: number
  peer_n: number
  percentile: number
  peer_label: string
  verdict: 'over' | 'under' | 'in line'
  histogram: HistBin[]
}

export interface YearValue {
  year: number
  value: number
}

export interface SaleRow {
  date: string
  price: number | null
  deed_kind: string | null
  validity: string | null
}

export interface Report {
  drivers: Drivers | null
  equity: Equity | null
  assessment_history: YearValue[]
  sale_history: SaleRow[]
  screen_built: string | null
}

export interface CompRow {
  address: string
  sale_date: string
  sale_price: number | null
  price_adj_today: number | null
  livable_area: number | null
  distance_m: number | null
}

export interface Stats {
  properties: number
  within: number
  over: number
  under: number
  /** Within-range homes near the interval edge — "worth a closer look". */
  watch: number
  median_ratio: number | null
  screen_built: string | null
}

export interface LeaderRow {
  parcel_id: string
  address: string
  opa_market_value: number | null
  model_median: number | null
  ratio: number | null
  screen_z: number | null
  twin_n: number | null
  twin_ratio: number | null
}

export interface ParcelFeature {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: { id: string; flag: Flag; opa: number | null; model: number | null }
}

export interface ParcelCollection {
  type: 'FeatureCollection'
  features: ParcelFeature[]
}
