/** Anonymous usage analytics (PostHog), configured for a civic-trust site:
 * no cookies and nothing in browser storage (in-memory persistence, so no
 * device id outlives the page), no autocapture, no session recording — only
 * the explicit events below and manual pageviews. Every event names the route
 * ('property', 'map') instead of the URL, so no account number, query string
 * or hash reaches PostHog. Inits in production builds only so dev sessions
 * don't pollute the numbers. The token is a publishable client key.
 *
 * posthog-js loads in the background and calls made before it arrives are
 * queued. Nothing here imports it statically, so a browser that blocks it
 * still gets a working site. */
import type { CaptureResult } from 'posthog-js'

type Props = Record<string, unknown>
type Capture = (event: string, props?: Props) => void

const TOKEN = 'phc_xW4AqiFfnINktDcHGcS5Ugc14GZo0XICN9FhLGLPBJS'

let capture: Capture = () => {}
let route = ''

function originOf(referrer: unknown): string {
  try {
    return new URL(String(referrer)).origin
  } catch {
    return '$direct'
  }
}

/** posthog-js reads the browser's URL into several properties. The page's own
 * URL becomes the route the event was recorded on, a referrer keeps only its
 * origin, and the entry and previous-page URLs are dropped. */
function withRouteNames(event: CaptureResult | null): CaptureResult | null {
  if (!event) return null
  const name = String(event.properties.route ?? route)
  for (const props of [event.properties, event.$set ?? {}, event.$set_once ?? {}]) {
    for (const key of Object.keys(props)) {
      if (key === '$current_url' || key === '$pathname' || key === 'title') props[key] = name
      else if (key.endsWith('referrer')) props[key] = originOf(props[key])
      else if (key.endsWith('url') || key.endsWith('pathname')) delete props[key]
    }
  }
  return event
}

export function initAnalytics(): void {
  if (!import.meta.env.PROD || import.meta.env.VITE_ANALYTICS_ENABLED === 'false') return
  const queued: Parameters<Capture>[] = []
  capture = (...call) => queued.push(call)
  import('posthog-js').then(
    ({ default: posthog }) => {
      posthog.init(TOKEN, {
        api_host: 'https://us.i.posthog.com',
        persistence: 'memory',
        autocapture: false,
        capture_pageview: false, // manual, on router navigation
        disable_session_recording: true,
        // The flags request carries the landing URL and bypasses before_send.
        // The site reads no flags. This also skips PostHog's remote config, so
        // project settings cannot turn on capture this file does not ask for.
        advanced_disable_flags: true,
        before_send: withRouteNames,
      })
      capture = (event, props) => posthog.capture(event, props)
      for (const call of queued) capture(...call)
    },
    () => {
      capture = () => {}
    },
  )
}

export function trackPageview(name: string): void {
  route = name
  capture('$pageview', { route: name })
}

export function track(event: string, props?: Props): void {
  capture(event, { ...props, route })
}
