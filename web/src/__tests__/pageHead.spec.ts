import { describe, expect, it } from 'vitest'
import { pageHead } from '@/utils/pageHead'

describe('page metadata', () => {
  it('uses the canonical report path for aliases and synchronizes social metadata', () => {
    const head = pageHead({ name: 'annual-report', path: '/report', meta: {
      title: 'Assessment report', description: 'The report description', canonicalPath: '/reports/ty-2030',
    } })
    expect(head.link).toEqual([{ rel: 'canonical', href: 'https://www.nickhand.dev/fair-measure/reports/ty-2030' }])
    expect(head.meta).toEqual(expect.arrayContaining([
      { property: 'og:title', content: head.title },
      { name: 'twitter:title', content: head.title },
      { property: 'og:description', content: 'The report description' },
    ]))
  })

  it('keeps the root slash and removes trailing slashes from page canonical URLs', () => {
    expect(pageHead({ name: 'home', path: '/', meta: {} }).link[0]?.href)
      .toBe('https://www.nickhand.dev/fair-measure/')
    expect(pageHead({ name: 'appeal', path: '/appeal/', meta: {} }).link[0]?.href)
      .toBe('https://www.nickhand.dev/fair-measure/appeal')
  })

  it('does not assign an indexable canonical URL to admin or missing pages', () => {
    const head = pageHead({ name: 'admin', path: '/admin', meta: { noindex: true } })
    expect(head.link).toEqual([])
    expect(head.meta).toContainEqual({ name: 'robots', content: 'noindex, nofollow' })
  })
})
