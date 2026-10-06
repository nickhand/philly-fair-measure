import type { RouteLocationNormalizedLoaded } from 'vue-router'

const SITE_URL = 'https://www.nickhand.dev/fair-measure'
const DEFAULT_DESCRIPTION =
  "A free, independent check of Philadelphia property assessments. Enter your address, see if the city's value looks fair, and get the evidence to appeal."

/** Shared by generated HTML and subsequent browser navigation. */
export function pageHead(route: Pick<RouteLocationNormalizedLoaded, 'name' | 'path' | 'meta'>) {
  const label = (route.meta.title as string) ?? 'Fair Measure'
  const title = route.name === 'home' ? label : `${label} · Fair Measure`
  const description = (route.meta.description as string) ?? DEFAULT_DESCRIPTION
  const path = (route.meta.canonicalPath as string) ?? route.path.replace(/\/$/, '')
  const url = `${SITE_URL}${path || '/'}`
  return {
    title,
    link: route.meta.noindex ? [] : [{ rel: 'canonical', href: url }],
    meta: [
      { name: 'title', content: title },
      { name: 'description', content: description },
      { name: 'robots', content: route.meta.noindex
        ? 'noindex, nofollow'
        : 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1' },
      { property: 'og:title', content: title },
      { property: 'og:description', content: description },
      { property: 'og:url', content: url },
      { name: 'twitter:title', content: title },
      { name: 'twitter:description', content: description },
      { name: 'twitter:url', content: url },
    ],
  }
}
