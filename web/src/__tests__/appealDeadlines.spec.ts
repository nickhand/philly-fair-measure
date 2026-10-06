import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { createSSRApp, defineComponent, h, nextTick } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import TaxYearBanner from '@/components/ui/TaxYearBanner.vue'
import AppealView from '@/views/AppealView.vue'
import AppealSteps from '@/components/ui/AppealSteps.vue'
import { SITE } from '@/config/site'

// Deliberately distinct dates exercise the gap between deadlines even when the
// currently published cycle has both deadlines on the same date.
vi.mock('@/data/siteStats.json', () => ({
  default: {
    annual_report: {
      tax_year: 2027,
      appeal_deadlines: { first_level_review: '2026-09-01', formal_appeal: '2026-10-05' },
    },
  },
}))

const wrappers: VueWrapper[] = []

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
})

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.useRealTimers()
  localStorage.clear()
})

async function mountAppealSurfaces() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/property/:parcelId', name: 'property', component: { template: '<div />' } },
      { path: '/appeal', name: 'appeal', component: AppealView },
    ],
  })
  await router.push('/property/123456789')
  const wrapper = mount(
    defineComponent({
      components: { TaxYearBanner, AppealView },
      template: '<TaxYearBanner /><AppealView />',
    }),
    { global: { plugins: [router], stubs: { AddressSearch: true } } },
  )
  wrappers.push(wrapper)
  await nextTick()
  return wrapper
}

function prose(wrapper: Pick<VueWrapper, 'text'>) {
  return wrapper.text().replace(/\s+/g, ' ')
}

describe('appeal deadline messaging', () => {
  it('keeps both deadlines current through the FLR date in Philadelphia', async () => {
    // Already September 2 in UTC, but still September 1 in Philadelphia.
    vi.setSystemTime(new Date('2026-09-02T03:59:59.999Z'))
    const wrapper = await mountAppealSurfaces()
    const banner = wrapper.getComponent(TaxYearBanner)
    expect(prose(banner)).toContain(`First Level Reviews are due by ${SITE.flrDeadlineText}`)
    expect(prose(banner)).toContain(`formal appeals by ${SITE.appealDeadlineText}`)
    expect(banner.get('a').attributes('href')).toBe('/appeal?acct=123456789')
    expect(prose(wrapper.getComponent(AppealView))).toContain(
      `is due by ${SITE.flrDeadlineText}`,
    )
    expect(prose(wrapper.getComponent(AppealSteps))).toContain('Ask OPA for a')
  })

  it('switches only the expired deadline to past tense at Philadelphia midnight', async () => {
    vi.setSystemTime(new Date('2026-09-02T03:59:59.999Z'))
    const wrapper = await mountAppealSurfaces()
    await vi.advanceTimersByTimeAsync(1)

    const banner = prose(wrapper.getComponent(TaxYearBanner))
    expect(banner).toContain(`First Level Review deadline was ${SITE.flrDeadlineText}`)
    expect(banner).toContain(`Formal appeals are due by ${SITE.appealDeadlineText}`)
    const guide = prose(wrapper.getComponent(AppealView))
    expect(guide).toContain(`was due by ${SITE.flrDeadlineText}`)
    expect(guide).toContain(`is due by ${SITE.appealDeadlineText}`)
    expect(guide).not.toContain('Ask OPA for a')
    expect(guide).toContain('You do not need to wait for a First Level Review')
  })

  it('removes the banner and updates an open guide after the final deadline', async () => {
    vi.setSystemTime(new Date('2026-10-06T03:59:59.999Z'))
    const wrapper = await mountAppealSurfaces()
    expect(wrapper.find('[aria-label="Assessment timing notice"]').exists()).toBe(true)
    expect(prose(wrapper.getComponent(AppealView))).toContain(
      `is due by ${SITE.appealDeadlineText}`,
    )

    await vi.advanceTimersByTimeAsync(1)

    expect(wrapper.find('[aria-label="Assessment timing notice"]').exists()).toBe(false)
    const guide = prose(wrapper.getComponent(AppealView))
    expect(guide).toContain('review and appeal deadlines have passed')
    expect(guide).toContain(`was due by ${SITE.flrDeadlineText}`)
    expect(guide).toContain(`was due by ${SITE.appealDeadlineText}`)
    expect(guide).not.toContain('is due by')
    expect(guide).not.toContain('file a formal appeal')
    expect(guide).toContain('Keep your report')
  })

  it('renders past deadlines on a fresh visit and preserves useful property links', async () => {
    vi.setSystemTime(new Date('2026-10-06T04:00:00Z'))
    const wrapper = await mountAppealSurfaces()
    expect(wrapper.find('[aria-label="Assessment timing notice"]').exists()).toBe(false)

    const steps = mount(AppealSteps, { props: { parcelId: '123456789' } })
    wrappers.push(steps)
    await nextTick()
    expect(prose(steps)).toContain('Check your record and review past deadlines')
    expect(prose(steps)).toContain(`was ${SITE.flrDeadlineText}`)
    expect(prose(steps)).toContain(`was ${SITE.appealDeadlineText}`)
    expect(steps.findAll('a').map((a) => a.attributes('href'))).toEqual(
      expect.arrayContaining([
        'https://property.phila.gov/?p=123456789',
        'https://opainquiry.phila.gov/opa.apps/help/PropInq.aspx?acct_num=123456789',
        SITE.flrUrl,
        SITE.appealFormsUrl,
      ]),
    )
  })

  it.each(['focus', 'visibilitychange'])('refreshes a suspended tab on %s', async (event) => {
    vi.setSystemTime(new Date('2026-10-05T16:00:00Z'))
    const wrapper = await mountAppealSurfaces()
    // Jump the clock without firing timers, as happens while a tab is suspended.
    vi.setSystemTime(new Date('2026-10-06T04:00:00Z'))
    const target = event === 'focus' ? window : document
    target.dispatchEvent(new Event(event))
    await nextTick()
    expect(wrapper.find('[aria-label="Assessment timing notice"]').exists()).toBe(false)
    expect(prose(wrapper.getComponent(AppealView))).toContain('deadlines have passed')
    wrappers.splice(0).forEach((w) => w.unmount())
    expect(vi.getTimerCount()).toBe(0)
  })

  it('retains dismissal for the configured tax year', async () => {
    vi.setSystemTime(new Date('2026-08-31T16:00:00Z'))
    const wrapper = await mountAppealSurfaces()
    await wrapper.get('[aria-label="Dismiss this notice"]').trigger('click')
    expect(localStorage.getItem(`fm-ty${SITE.assessmentTaxYear}-banner-dismissed`)).toBe('1')
    expect(wrapper.find('[aria-label="Assessment timing notice"]').exists()).toBe(false)
    const remounted = await mountAppealSurfaces()
    expect(remounted.find('[aria-label="Assessment timing notice"]').exists()).toBe(false)
  })

  it('hydrates date-neutral HTML after a deadline with a query-prefilled account', async () => {
    const Harness = defineComponent({ render: () => h('div', [h(TaxYearBanner), h(AppealView)]) })
    async function createGuide(url: string) {
      const router = createRouter({ history: createMemoryHistory(), routes: [
        { path: '/appeal', name: 'appeal', component: AppealView },
      ] })
      await router.push(url)
      return createSSRApp(Harness).use(router)
    }
    vi.setSystemTime(new Date('2026-08-31T16:00:00Z'))
    const html = await renderToString(await createGuide('/appeal'))
    expect(html).toContain('First Level Review deadline')
    expect(html).not.toMatch(/is due by|was due by|deadlines have passed|Assessment timing notice/)
    vi.setSystemTime(new Date('2026-10-06T04:00:00Z'))
    expect(await renderToString(await createGuide('/appeal'))).toBe(html)

    const container = document.createElement('div')
    container.innerHTML = html
    document.body.append(container)
    const errors = vi.spyOn(console, 'error')
    const warnings = vi.spyOn(console, 'warn')
    const client = await createGuide('/appeal?acct=123456789')
    try {
      client.mount(container)
      await nextTick()
      expect(container.textContent).toContain('deadlines have passed')
      expect(container.querySelector<HTMLInputElement>('#acct')?.value).toBe('123456789')
      expect(container.querySelector('a[href="https://property.phila.gov/?p=123456789"]')).not.toBeNull()
      expect([...errors.mock.calls, ...warnings.mock.calls].flat().join(' ')).not.toMatch(/hydration|mismatch/i)
    } finally {
      client.unmount()
      container.remove()
      errors.mockRestore()
      warnings.mockRestore()
    }
  })
})
