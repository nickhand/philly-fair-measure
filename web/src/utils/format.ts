const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

/** $441,900 — the everyday money format. */
export function money(value: number | null | undefined): string {
  return value == null ? '—' : usd.format(value)
}

/** $442k / $1.2M — compact for axes and small screens. */
export function moneyCompact(value: number | null | undefined): string {
  if (value == null) return '—'
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (abs >= 1_000) return `$${Math.round(value / 1_000)}k`
  return usd.format(value)
}

/** +$78,000 / −$40,000 — signed money for driver effects. */
export function moneySigned(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value >= 0 ? '+' : '−'
  return `${sign}${usd.format(Math.abs(value))}`
}

/** 0.85 → "85%" */
export function pct(value: number | null | undefined, digits = 0): string {
  return value == null ? '—' : `${(value * 100).toFixed(digits)}%`
}

export function num(value: number | null | undefined): string {
  return value == null ? '—' : new Intl.NumberFormat('en-US').format(value)
}
