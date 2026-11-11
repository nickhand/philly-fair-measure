import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import type { Router } from 'vue-router'
import stats from '@/data/siteStats.json'

type Props = Record<string, unknown>
const posthog = {
  init: vi.fn<(token: string, config: Props) => void>(),
  capture: vi.fn<(event: string, props?: Props) => void>(),
}

function pageviews(): unknown[] {
  return posthog.capture.mock.calls
    .filter(([event]) => event === '$pageview')
    .map(([, props]) => props?.path)
}

function mountedApp(): App | undefined {
  return (document.querySelector('#app') as (Element & { __vue_app__?: App }) | null)?.__vue_app__
}

/** Load the site's entry module at `path`, as a visitor's browser does. */
async function openSite(path: string): Promise<Router> {
  window.history.replaceState(null, '', path)
  document.body.innerHTML = '<div id="app"></div>'
  await import('@/main')
  await vi.waitFor(() => expect(document.querySelector('main h1')).not.toBeNull(), { timeout: 2000 })
  return mountedApp()!.config.globalProperties.$router
}

const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve))

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('PROD', true)
  vi.stubEnv('VITE_ANALYTICS_ENABLED', 'true')
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))
  posthog.init.mockClear()
  posthog.capture.mockClear()
})

afterEach(() => {
  mountedApp()?.unmount()
  vi.doUnmock('posthog-js')
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('analytics', () => {
  it('mounts the app when the browser blocks the analytics library', async () => {
    vi.doMock('posthog-js', () => {
      throw new Error('net::ERR_BLOCKED_BY_CLIENT')
    })
    await openSite('/property/000000000')
    expect(document.querySelector('main h1')?.textContent).toContain('We could not find that property')
  })

  it('delivers events recorded before the library loads, in order, after init', async () => {
    vi.doMock('posthog-js', () => ({ default: posthog }))
    const { initAnalytics, track, trackPageview } = await import('@/lib/analytics')
    initAnalytics()
    trackPageview('/map')
    track('map_filter_toggled', { group: 'condos', on: true })
    await vi.waitFor(() => expect(posthog.capture).toHaveBeenCalledTimes(2))
    expect(posthog.capture.mock.calls).toEqual([
      ['$pageview', { path: '/map' }],
      ['map_filter_toggled', { group: 'condos', on: true }],
    ])
    expect(posthog.init).toHaveBeenCalledOnce()
    expect(posthog.init.mock.invocationCallOrder[0]).toBeLessThan(posthog.capture.mock.invocationCallOrder[0]!)
  })

  it('sends nothing when analytics is off', async () => {
    vi.stubEnv('VITE_ANALYTICS_ENABLED', 'false')
    vi.doMock('posthog-js', () => ({ default: posthog }))
    const { initAnalytics, track } = await import('@/lib/analytics')
    initAnalytics()
    track('comps_shown')
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(posthog.init).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
  })

  it('keeps focus and sends no pageview when only the hash changes', async () => {
    vi.doMock('posthog-js', () => ({ default: posthog }))
    const report = `/reports/ty-${stats.annual_report.tax_year}`
    const router = await openSite(report)
    await nextFrame()
    const link = document.querySelector<HTMLAnchorElement>('a[href="#finding"]')!
    link.focus()
    await router.push(`${report}#finding`)
    await nextFrame()
    expect(document.activeElement).toBe(link)

    await router.push('/findings')
    await nextFrame()
    expect(document.activeElement?.textContent).toContain('What we found')
    await vi.waitFor(() => expect(pageviews()).toEqual([report, '/findings']))
  })
})
