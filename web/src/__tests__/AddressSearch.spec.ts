import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AddressSearch from '@/components/search/AddressSearch.vue'

const HITS = [
  { parcel_id: 'p1', address: '108 ELFRETHS ALY', opa_market_value: 441_900 },
  { parcel_id: 'p2', address: '110 ELFRETHS ALY', opa_market_value: 310_000 },
]

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => HITS })),
  )
})

async function type(w: ReturnType<typeof mount>, text: string) {
  await w.find('input').setValue(text)
  vi.advanceTimersByTime(250) // past the debounce
  await flushPromises()
}

describe('AddressSearch', () => {
  it('implements the ARIA combobox pattern', async () => {
    const w = mount(AddressSearch)
    const input = w.find('input')
    expect(input.attributes('role')).toBe('combobox')
    expect(input.attributes('aria-expanded')).toBe('false')
    await type(w, 'elfreths')
    expect(input.attributes('aria-expanded')).toBe('true')
    const options = w.findAll('[role="option"]')
    expect(options).toHaveLength(2)
    expect(options[0]!.text()).toContain('108 ELFRETHS ALY')
  })

  it('supports arrow keys + enter and emits the selected hit', async () => {
    const w = mount(AddressSearch)
    await type(w, 'elfreths')
    const input = w.find('input')
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(input.attributes('aria-activedescendant')).toMatch(/-opt-1$/)
    await input.trigger('keydown', { key: 'Enter' })
    expect(w.emitted('select')![0]![0]).toMatchObject({ parcel_id: 'p2' })
  })

  it('closes on Escape', async () => {
    const w = mount(AddressSearch)
    await type(w, 'elfreths')
    await w.find('input').trigger('keydown', { key: 'Escape' })
    expect(w.find('input').attributes('aria-expanded')).toBe('false')
  })

  it('shows a friendly empty state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => [] })),
    )
    const w = mount(AddressSearch)
    await type(w, 'zzzz')
    expect(w.text()).toContain('No matches yet')
  })
})
