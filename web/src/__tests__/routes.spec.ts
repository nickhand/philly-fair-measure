import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from '@/router'

const router = createRouter({ history: createMemoryHistory(), routes })

describe('routes', () => {
  it('serves the map from /map', () => {
    expect(router.resolve('/map').name).toBe('map')
  })

  it.each(['/admin', '/leaderboards'])('shows the not-found page at %s', (path) => {
    expect(router.resolve(path).name).toBe('not-found')
  })
})
