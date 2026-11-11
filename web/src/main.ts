import './assets/main.css'

import { ViteSSG } from 'vite-ssg'
import { START_LOCATION } from 'vue-router'
import App from './App.vue'
import { initAnalytics, trackPageview } from './lib/analytics'
import { routes, scrollBehavior } from './router'

const withoutHash = (fullPath: string) => fullPath.split('#')[0]

export const createApp = ViteSSG(
  App,
  { routes, base: import.meta.env.BASE_URL, scrollBehavior },
  ({ router }) => {
    if (!import.meta.env.SSR) {
      initAnalytics()
      router.afterEach((to, from, failure) => {
        if (failure) return
        // An in-page link changes only the hash. The visitor is still on the
        // same page, so their focus stays put and no pageview is counted.
        if (from !== START_LOCATION && withoutHash(to.fullPath) === withoutHash(from.fullPath)) return
        trackPageview(String(to.name))
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
