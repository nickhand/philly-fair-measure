import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import MapView from '@/views/MapView.vue'
import AddressSearch from '@/components/search/AddressSearch.vue'

/** A stand-in for maplibre's Map that keeps the library's loading contract
 * (maplibre 6): addSource, addLayer and setFilter throw "Style is not done
 * loading." and getStyle returns nothing until the style JSON is parsed
 * (`Style._checkLoaded`), while isStyleLoaded() stays false until every
 * source's tiles and the sprite have loaded too (`Style.loaded`). */
const fake = vi.hoisted(() => {
  type Handler = (event?: unknown) => void
  type BasemapLayer = { id: string; type: string; paint: Record<string, unknown> }
  class FakeMap {
    static last: FakeMap
    styleParsed = false
    resourcesLoaded = false
    zoom = 11.4
    center: [number, number] | null = null
    /** A few of Positron's own layers with its own colours. */
    basemap: BasemapLayer[] = [
      { id: 'background', type: 'background', paint: { 'background-color': 'rgb(242,243,240)' } },
      { id: 'water', type: 'fill', paint: { 'fill-color': 'rgb(194, 200, 202)' } },
      { id: 'highway_minor', type: 'line', paint: { 'line-color': 'hsl(0,0%,88%)' } },
      { id: 'label_city', type: 'symbol', paint: { 'text-color': '#000', 'text-halo-color': '#fff' } },
    ]
    layers = new Map<string, { filter?: unknown }>()
    sources = new Map<string, { data: unknown; setData: (d: unknown) => void }>()
    handlers = new Map<string, Handler[]>()
    rendered: Array<{ properties: Record<string, unknown> }> = []
    constructor() {
      FakeMap.last = this
    }
    private checkLoaded() {
      if (!this.styleParsed) throw new Error('Style is not done loading.')
    }
    /** The events maplibre 6.11 fires on /map's first load, in the order a
     * headless Chrome trace recorded. No styledata event sees isStyleLoaded()
     * true. `load` fires once the tiles are in. */
    loadStyle() {
      this.styleParsed = true
      this.fire('styledata')
      this.fire('style.load')
      this.fire('styledata')
      this.fire('styledata')
      this.resourcesLoaded = true
      this.fire('load')
      this.fire('idle')
    }
    paint(layerId: string, property: string) {
      return this.basemap.find((l) => l.id === layerId)?.paint[property]
    }
    fire(event: string, payload?: unknown) {
      for (const h of this.handlers.get(event) ?? []) h(payload)
    }
    on(event: string, layerOrHandler: string | Handler, handler?: Handler) {
      if (typeof layerOrHandler !== 'function') return this
      this.handlers.set(event, [...(this.handlers.get(event) ?? []), layerOrHandler])
      return this
    }
    once(event: string, handler: Handler) {
      return this.on(event, handler)
    }
    addControl() {}
    remove() {}
    isStyleLoaded() {
      return this.styleParsed && this.resourcesLoaded
    }
    getStyle() {
      return this.styleParsed ? { layers: this.basemap } : undefined
    }
    setPaintProperty(layerId: string, property: string, value: unknown) {
      const layer = this.basemap.find((l) => l.id === layerId)
      if (layer) layer.paint[property] = value
    }
    getLayer(id: string) {
      return this.layers.get(id)
    }
    getSource(id: string) {
      return this.sources.get(id)
    }
    addSource(id: string, spec: { data: unknown }) {
      this.checkLoaded()
      const source = {
        data: spec.data,
        setData(d: unknown) {
          source.data = d
        },
      }
      this.sources.set(id, source)
    }
    addLayer(spec: { id: string; filter?: unknown }) {
      this.checkLoaded()
      this.layers.set(spec.id, { filter: spec.filter })
    }
    setFilter(id: string, filter: unknown) {
      this.checkLoaded()
      const layer = this.layers.get(id)
      if (layer) layer.filter = filter
    }
    getZoom() {
      return this.zoom
    }
    getBounds() {
      return { getWest: () => -75.2, getSouth: () => 39.9, getEast: () => -75.1, getNorth: () => 40 }
    }
    jumpTo(camera: { center: [number, number]; zoom: number }) {
      this.center = camera.center
      this.zoom = camera.zoom
    }
    flyTo(camera: { center: [number, number]; zoom: number }) {
      this.jumpTo(camera)
    }
    getCanvas() {
      return { style: {} }
    }
    queryRenderedFeatures() {
      return this.rendered
    }
  }
  return { FakeMap }
})

vi.mock('maplibre-gl', () => ({
  Map: fake.FakeMap,
  NavigationControl: class {},
  GeolocateControl: class {},
  setWorkerUrl: () => {},
}))
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'worker.js' }))

function home(id: string, address: string, lon: number, lat: number) {
  return {
    parcel_id: id,
    address,
    category: 'SINGLE FAMILY',
    model_family: 'residential',
    interval_method: 'bayesian_posterior',
    opa_market_value: 300_000,
    model_median: 250_000,
    model_pi_low_90: 200_000,
    model_pi_high_90: 280_000,
    ratio: 1.2,
    screen_z: 2.5,
    flag: 'over_assessed_candidate',
    attention: null,
    new_build: false,
    twin_n: null,
    twin_ratio: null,
    lon,
    lat,
    signals: {},
  }
}

const PRICE = home('591073500', '1154 E PRICE ST', -75.17, 40.05)
const ELFRETHS = home('052174500', '108 ELFRETHS ALY', -75.1425, 39.9527)

/** Responses by API path; a path mapped to a pending promise answers when the
 * test resolves it. Aborted requests reject the way fetch does. */
let routes: Record<string, () => Promise<unknown>>
function respondWith(body: unknown) {
  return () => Promise.resolve(body)
}
function held() {
  let release!: (body: unknown) => void
  let fail!: (err: Error) => void
  const promise = new Promise<unknown>((resolve, reject) => {
    release = resolve
    fail = reject
  })
  return { route: () => promise, release, fail }
}

beforeEach(() => {
  routes = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: { signal?: AbortSignal }) => {
      const path = url.split('?')[0]!
      const answer = routes[path]?.() ?? Promise.reject(new Error(`no route for ${url}`))
      const aborted = new Promise<never>((_, reject) =>
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError')),
        ),
      )
      return Promise.race([answer, aborted]).then((body) => ({
        ok: true,
        status: 200,
        json: async () => body,
      }))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/map', name: 'map', component: MapView },
      { path: '/property/:parcelId', name: 'property', component: { template: '<p>report</p>' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(MapView, { global: { plugins: [router] } })
  return { wrapper, router, map: fake.FakeMap.last }
}

function sheetFor(wrapper: Awaited<ReturnType<typeof mountAt>>['wrapper']) {
  return wrapper.find('[role="dialog"]')
}

function selectedRing(map: InstanceType<typeof fake.FakeMap>) {
  return map.getLayer('fm-dot-selected')?.filter
}

describe('MapView', () => {
  it('opens a deep-linked home when its record arrives before the basemap style', async () => {
    routes['/api/property/591073500'] = respondWith(PRICE)
    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [] })
    const { wrapper, router, map } = await mountAt('/map?parcel=591073500')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/map?parcel=591073500')
    expect(sheetFor(wrapper).attributes('aria-label')).toBe('1154 E PRICE ST')
    expect(map.center).toEqual([-75.17, 40.05])

    map.loadStyle()
    await flushPromises()
    expect(selectedRing(map)).toEqual(['==', ['get', 'id'], '591073500'])
  })

  it('draws the basemap in the Fair Measure palette once the style loads', async () => {
    const { map } = await mountAt('/map')
    map.loadStyle()
    await flushPromises()

    expect(map.paint('background', 'background-color')).toBe('#eef0f1')
    expect(map.paint('water', 'fill-color')).toBe('#ccd8e2')
    expect(map.paint('highway_minor', 'line-color')).toBe('#ffffff')
    expect(map.paint('label_city', 'text-halo-color')).toBe('#ffffff')
    // the label grey itself is the style module's choice (PR #18 changes it), so
    // this asserts only that Positron's black is gone
    expect(map.paint('label_city', 'text-color')).not.toBe('#000')
  })

  it('keeps the newest search pick when an older lookup answers last', async () => {
    const slow = held()
    routes['/api/property/591073500'] = slow.route
    routes['/api/property/052174500'] = respondWith(ELFRETHS)
    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [] })
    const { wrapper, map } = await mountAt('/map')
    map.loadStyle()
    const search = wrapper.findComponent(AddressSearch)

    search.vm.$emit('select', { parcel_id: '591073500', address: '1154 E PRICE ST', opa_market_value: null })
    search.vm.$emit('select', { parcel_id: '052174500', address: '108 ELFRETHS ALY', opa_market_value: null })
    await flushPromises()
    slow.release(PRICE)
    await flushPromises()

    expect(sheetFor(wrapper).attributes('aria-label')).toBe('108 ELFRETHS ALY')
    expect(map.center).toEqual([-75.1425, 39.9527])
    expect(selectedRing(map)).toEqual(['==', ['get', 'id'], '052174500'])
  })

  it('keeps a stacked-homes list open when an earlier dot lookup answers late', async () => {
    const slow = held()
    routes['/api/property/591073500'] = slow.route
    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [] })
    const { wrapper, map } = await mountAt('/map')
    map.loadStyle()

    map.rendered = [{ properties: { id: '591073500', address: '1154 E PRICE ST' } }]
    map.fire('click', { point: { x: 10, y: 10 } })
    map.rendered = [
      { properties: { id: 'u1', address: '3600 CONSHOHOCKEN AVE #1001' } },
      { properties: { id: 'u2', address: '3600 CONSHOHOCKEN AVE #1002' } },
    ]
    map.fire('click', { point: { x: 50, y: 50 } })
    slow.release(PRICE)
    await flushPromises()

    expect(sheetFor(wrapper).exists()).toBe(false)
    expect(wrapper.text()).toContain('2 homes share this spot')
  })

  it('says when the street-level layer leaves homes out', async () => {
    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [], truncated: true })
    const { wrapper, map } = await mountAt('/map')
    map.loadStyle()
    map.zoom = 15
    map.fire('moveend')
    await flushPromises()
    expect(wrapper.text()).toContain('Some homes in this view are hidden')

    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [], truncated: false })
    map.fire('moveend')
    await flushPromises()
    expect(wrapper.text()).not.toContain('Some homes in this view are hidden')

    // an API without the flag (the deployed one, before this change) shows no hint
    routes['/api/parcels'] = respondWith({ type: 'FeatureCollection', features: [] })
    map.fire('moveend')
    await flushPromises()
    expect(wrapper.text()).not.toContain('Some homes in this view are hidden')
  })

  it('drops a street-level request that fails after the map zooms back out', async () => {
    const slow = held()
    routes['/api/parcels'] = slow.route
    const { wrapper, map } = await mountAt('/map')
    map.loadStyle()
    map.zoom = 15
    map.fire('moveend')
    map.zoom = 12
    map.fire('moveend')
    slow.fail(new TypeError('Failed to fetch'))
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
