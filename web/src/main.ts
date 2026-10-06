import './assets/main.css'

import { ViteSSG } from 'vite-ssg'
import App from './App.vue'
import { routes, scrollBehavior } from './router'

export const createApp = ViteSSG(
  App,
  { routes, base: import.meta.env.BASE_URL, scrollBehavior },
  async ({ router }) => {
    if (!import.meta.env.SSR) {
      const { initAnalytics, trackPageview } = await import('./lib/analytics')
      initAnalytics()
      router.afterEach((to, _from, failure) => {
        if (failure) return
        trackPageview(to.fullPath)
        requestAnimationFrame(() => {
          const heading = document.querySelector('main h1') as HTMLElement | null
          heading?.setAttribute('tabindex', '-1')
          heading?.focus({ preventScroll: true })
        })
      })
    }
  },
  {
    // Vite dev and the dynamic-route fallback have an empty app container.
    // Only hydrate documents that actually contain generated Vue markup.
    hydration: !import.meta.env.SSR &&
      document.querySelector('#app')?.getAttribute('data-server-rendered') === 'true',
  },
)
