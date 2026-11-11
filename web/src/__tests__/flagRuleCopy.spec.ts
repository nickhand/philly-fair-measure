import { describe, expect, it } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import type { Component } from 'vue'
import MethodologyView from '@/views/MethodologyView.vue'
import TrustView from '@/views/TrustView.vue'

// The screen's agreement gate needs two bands, and only houses have two. A
// condo is flagged on its one model's band (validation/opa.py,
// finalize_screen), so on the 2026-07-14 screen none of the 4,401 condo flags
// has a second band. Copy may promise agreement only for houses, and must say
// how condos are flagged.

const sentences = (view: Component): string[] =>
  mount(view, { global: { stubs: { RouterLink: RouterLinkStub } } })
    .text()
    .replace(/\s+/g, ' ')
    .split(/(?<=[.!?])\s+/)

const AGREEMENT = /\b(two|both)\b.*\b(methods|ways)\b.*\bagree|\bagree.*\b(two|both)\b.*\b(methods|ways)\b/i

describe.each([
  ['Trust page', TrustView],
  ['Methodology page', MethodologyView],
])('%s flag-rule copy', (_name, view) => {
  const page = sentences(view)

  it('promises two-method agreement only for houses', () => {
    const claims = page.filter((s) => AGREEMENT.test(s))
    expect(claims.length).toBeGreaterThan(0)
    for (const claim of claims) expect(claim).toMatch(/\bhouses?\b/i)
  })

  it('says how a condo is flagged', () => {
    expect(page.some((s) => /\bcondos?\b/i.test(s) && /\bflag/i.test(s))).toBe(true)
  })
})
