import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import IntervalStrip from '@/components/viz/IntervalStrip.vue'

// jsdom has no ResizeObserver
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
)

const base = {
  low: 400_000,
  high: 700_000,
  median: 520_000,
  opa: 441_900,
  flag: 'within_range' as const,
}

describe('IntervalStrip', () => {
  it('describes the whole graphic in one accessible sentence', () => {
    const w = mount(IntervalStrip, { props: base })
    const svg = w.find('svg')
    expect(svg.attributes('role')).toBe('img')
    expect(svg.attributes('aria-label')).toContain('$400,000')
    expect(svg.attributes('aria-label')).toContain('$700,000')
    expect(svg.attributes('aria-label')).toContain('inside')
  })

  it('says "outside" when the city value leaves the range', () => {
    const w = mount(IntervalStrip, {
      props: { ...base, opa: 900_000, flag: 'over_assessed_candidate' as const },
    })
    expect(w.find('svg').attributes('aria-label')).toContain('outside')
  })

  it('offers the numbers as a table fallback', () => {
    const w = mount(IntervalStrip, { props: base })
    expect(w.find('details table').exists()).toBe(true)
    expect(w.text()).toContain('City’s value')
    expect(w.text()).toContain('$441,900')
  })

  it('positions the city marker between low and high bounds on the scale', () => {
    const w = mount(IntervalStrip, { props: base })
    // the marker group is translated to the OPA x position
    const marker = w.find('g')
    const transform = marker.attributes('transform') ?? ''
    const x = Number(/translate\(([\d.]+)/.exec(transform)?.[1])
    expect(x).toBeGreaterThan(0)
    expect(x).toBeLessThan(640)
  })

  it('shortens labels and folds the bounds into the caption on phone widths', async () => {
    // a ResizeObserver that reports a phone-sized wrapper on observe()
    vi.stubGlobal(
      'ResizeObserver',
      class {
        cb: ResizeObserverCallback
        constructor(cb: ResizeObserverCallback) {
          this.cb = cb
        }
        observe() {
          this.cb(
            [{ contentRect: { width: 340 } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          )
        }
        unobserve() {}
        disconnect() {}
      },
    )
    const w = mount(IntervalStrip, { props: base })
    await w.vm.$nextTick()
    const svgText = w.find('svg').text()
    expect(svgText).toContain('City $442k')
    expect(svgText).toContain('Ours $520k')
    expect(svgText).not.toContain('City value')
    expect(svgText).not.toContain('Our estimate')
    // the bounds live in the caption, not as edge labels that get cut off
    expect(svgText).toContain("range we're 90% sure about: $400k–$700k")
  })
})
