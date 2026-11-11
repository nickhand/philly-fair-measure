import { describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import FindingsView from '@/views/FindingsView.vue'

// Sentinel values that cannot collide with any other figure on the page, so a
// match means the page printed that export.
vi.mock('@/data/siteStats.json', async (importOriginal) => {
  type Stats = typeof import('@/data/siteStats.json')
  const { default: stats } = await importOriginal<{ default: Stats }>()
  return {
    default: {
      ...stats,
      tax_shift: {
        ...stats.tax_shift,
        new_revenue_musd: 98765,
        base_change_pct: 43.21,
        priciest_home_usd: 4321,
      },
    },
  }
})

const text = mount(FindingsView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  .text()
  .replace(/\s+/g, ' ')

describe('Findings page tax finding', () => {
  it('shows the per-home change for the priciest fifth', () => {
    expect(text).toContain('$4321 more')
  })

  it('states no citywide revenue or assessment-base figure', () => {
    expect(text).not.toMatch(/98,?765/)
    expect(text).not.toContain('43.21')
  })
})
