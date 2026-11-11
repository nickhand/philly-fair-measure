import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PropertyView from '@/views/PropertyView.vue'

function home(id: string, address: string) {
  return {
    parcel_id: id,
    address,
    category: 'SINGLE FAMILY',
    model_family: 'residential',
    interval_method: 'bayesian_posterior',
    opa_market_value: 300_000,
    model_median: 290_000,
    model_pi_low_90: 250_000,
    model_pi_high_90: 340_000,
    ratio: 1.03,
    screen_z: 0.2,
    flag: 'within_range',
    attention: null,
    new_build: false,
    twin_n: null,
    twin_ratio: null,
    lon: -75.14,
    lat: 39.95,
    signals: {
      aerial_change: false,
      aerial_pair: null,
      vacancy_complaints_5y: 0,
      unpermitted_work_complaints_5y: 0,
      owner_occupied: false,
      linked_parcels: 1,
    },
  }
}

const ELFRETHS = home('052174500', '108 ELFRETHS ALY')
const PRICE = home('591073500', '1154 E PRICE ST')
const REPORT = {
  drivers: null,
  equity: null,
  assessment_history: [],
  sale_history: [],
  screen_built: '2026-07-14',
}
const EMPTY_DATA_COPY = [
  'Not enough similar homes nearby',
  'No assessment history available',
  'We can’t break down the estimate',
]

/** Responses by API path. A route answers with a status and body, or with a
 * pending promise the test settles later. */
type Answer = { status: number; body?: unknown }
let routes: Record<string, () => Promise<Answer>>
const ok = (body: unknown) => () => Promise.resolve({ status: 200, body })
const failing = (status: number) => () => Promise.resolve({ status })
function held() {
  let release!: (body: unknown, status?: number) => void
  const promise = new Promise<Answer>((resolve) => {
    release = (body, status = 200) => resolve({ status, body })
  })
  return { route: () => promise, release }
}

beforeEach(() => {
  routes = {}
  // jsdom has no ResizeObserver; the report's charts observe their width
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const answer = routes[url]
      if (!answer) throw new TypeError(`Failed to fetch ${url}`)
      const { status, body } = await answer()
      return { ok: status < 400, status, json: async () => body }
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function mountAt(parcelId: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<p>home</p>' } },
      { path: '/map', name: 'map', component: { template: '<p>map</p>' } },
      { path: '/methodology', component: { template: '<p>methods</p>' } },
      { path: '/property/:parcelId', name: 'property', component: PropertyView, props: true },
    ],
  })
  await router.push(`/property/${parcelId}`)
  await router.isReady()
  return mount(PropertyView, { props: { parcelId }, global: { plugins: [router] } })
}

function button(w: Awaited<ReturnType<typeof mountAt>>, label: string) {
  const match = w.findAll('button').find((b) => b.text() === label)
  if (!match) throw new Error(`no button "${label}"`)
  return match
}

function hasButton(w: Awaited<ReturnType<typeof mountAt>>, label: string) {
  return w.findAll('button').some((b) => b.text() === label)
}

describe('PropertyView', () => {
  it('shows an error with a retry when the report request fails, not empty-data copy', async () => {
    routes['/api/property/052174500'] = ok(ELFRETHS)
    routes['/api/property/052174500/report'] = failing(500)
    const w = await mountAt('052174500')
    await flushPromises()

    expect(w.find('h1').text()).toBe('108 ELFRETHS ALY')
    expect(w.find('[role="alert"]').exists()).toBe(true)
    for (const copy of EMPTY_DATA_COPY) expect(w.text()).not.toContain(copy)

    routes['/api/property/052174500/report'] = ok(REPORT)
    await button(w, 'Try again').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.text()).toContain('Data updated 2026-07-14')
  })

  it('keeps the current home when the previous home answers late', async () => {
    const slowCore = held()
    routes['/api/property/052174500'] = slowCore.route
    routes['/api/property/591073500'] = ok(PRICE)
    routes['/api/property/591073500/report'] = ok(REPORT)
    const w = await mountAt('052174500')

    await w.setProps({ parcelId: '591073500' })
    await flushPromises()
    slowCore.release(ELFRETHS)
    await flushPromises()

    expect(w.find('h1').text()).toBe('1154 E PRICE ST')
  })

  it('keeps the current home when the previous home fails late', async () => {
    const slowCore = held()
    routes['/api/property/052174500'] = slowCore.route
    routes['/api/property/591073500'] = ok(PRICE)
    routes['/api/property/591073500/report'] = ok(REPORT)
    const w = await mountAt('052174500')

    await w.setProps({ parcelId: '591073500' })
    await flushPromises()
    slowCore.release({ detail: 'internal server error' }, 500)
    await flushPromises()

    expect(w.find('h1').text()).toBe('1154 E PRICE ST')
  })

  it('keeps the current home’s report and comps when the previous ones answer late', async () => {
    const slowReport = held()
    const slowComps = held()
    routes['/api/property/052174500'] = ok(ELFRETHS)
    routes['/api/property/052174500/report'] = slowReport.route
    routes['/api/property/052174500/comps'] = slowComps.route
    routes['/api/property/591073500'] = ok(PRICE)
    routes['/api/property/591073500/report'] = held().route
    const w = await mountAt('052174500')
    await flushPromises()
    await button(w, 'Show comparable sales').trigger('click')

    await w.setProps({ parcelId: '591073500' })
    await flushPromises()
    slowReport.release(REPORT)
    slowComps.release([
      {
        address: '110 ELFRETHS ALY',
        sale_date: '2025-05-01',
        sale_price: 400_000,
        price_adj_today: 410_000,
        livable_area: 1_000,
        distance_m: 20,
        similarity: 0.5,
      },
    ])
    await flushPromises()

    expect(w.find('h1').text()).toBe('1154 E PRICE ST')
    expect(w.text()).not.toContain('Data updated 2026-07-14')
    expect(w.text()).not.toContain('110 ELFRETHS ALY')
    expect(hasButton(w, 'Show comparable sales')).toBe(true)
  })

  it('shows no tax-balance chip, even when an older API still sends the June 2022 flag', async () => {
    routes['/api/property/591073500'] = ok({
      ...PRICE,
      signals: { ...PRICE.signals, owner_occupied: true, tax_delinquent: true },
    })
    routes['/api/property/591073500/report'] = ok(REPORT)
    const w = await mountAt('591073500')
    await flushPromises()

    const panel = w
      .findAll('section')
      .find((s) => s.text().startsWith('Other things we see in city data'))!
    expect(panel.text()).toContain('Owner-occupied (homestead exemption)')
    expect(panel.text()).not.toMatch(/tax/i)
  })

  it('describes the range as one tested 90% range', async () => {
    routes['/api/property/052174500'] = ok(ELFRETHS)
    routes['/api/property/052174500/report'] = ok(REPORT)
    const w = await mountAt('052174500')
    await flushPromises()

    expect(w.text()).toContain(
      'Our 90% range. In testing, about 9 in 10 sale prices fell inside a range built this way.',
    )
    expect(w.text()).not.toContain('two independent ways')
  })
})
