const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

const NO_DATA = 'N/A'

/** $441,900. The everyday money format. */
export function money(value: number | null | undefined): string {
  return value == null ? NO_DATA : usd.format(value)
}

/** $442k / $1.2M, compact for axes and small screens. Negatives carry the
 * sign in front of the currency symbol (−$1.5M), matching moneySigned. */
export function moneyCompact(value: number | null | undefined): string {
  if (value == null) return NO_DATA
  const sign = value < 0 ? '−' : ''
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (abs >= 1_000) return `${sign}$${Math.round(abs / 1_000)}k`
  return `${sign}${usd.format(abs)}`
}

/** +$78,000 / −$40,000, signed money for driver effects. */
export function moneySigned(value: number | null | undefined): string {
  if (value == null) return NO_DATA
  const sign = value >= 0 ? '+' : '−'
  return `${sign}${usd.format(Math.abs(value))}`
}

/** 0.85 → "85%" */
export function pct(value: number | null | undefined, digits = 0): string {
  return value == null ? NO_DATA : `${(value * 100).toFixed(digits)}%`
}

export function num(value: number | null | undefined): string {
  return value == null ? NO_DATA : new Intl.NumberFormat('en-US').format(value)
}
