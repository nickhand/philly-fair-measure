import { describe, expect, it } from 'vitest'
import { money, moneyCompact, moneySigned, pct } from '@/utils/format'

describe('money', () => {
  it('formats whole dollars', () => {
    expect(money(441_900)).toBe('$441,900')
  })
  it('renders N/A for missing values', () => {
    expect(money(null)).toBe('N/A')
    expect(money(undefined)).toBe('N/A')
  })
})

describe('moneyCompact', () => {
  it('uses k and M', () => {
    expect(moneyCompact(442_000)).toBe('$442k')
    expect(moneyCompact(1_200_000)).toBe('$1.2M')
    expect(moneyCompact(950)).toBe('$950')
  })
})

describe('moneySigned', () => {
  it('carries the sign explicitly', () => {
    expect(moneySigned(78_000)).toBe('+$78,000')
    expect(moneySigned(-40_000)).toBe('−$40,000')
  })
})

describe('pct', () => {
  it('formats ratios as percentages', () => {
    expect(pct(0.85)).toBe('85%')
    expect(pct(1.181, 1)).toBe('118.1%')
    expect(pct(null)).toBe('N/A')
  })
})
