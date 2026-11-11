/** Anonymous usage analytics (PostHog), configured for a civic-trust site:
 * no cookies (localStorage persistence only), no autocapture, no session
 * recording — only the explicit events below and manual pageviews. Inits in
 * production builds only so dev sessions don't pollute the numbers. The token
 * is a publishable client key.
 *
 * posthog-js loads in the background and calls made before it arrives are
 * queued. Nothing here imports it statically, so a browser that blocks it
 * still gets a working site. */
type Props = Record<string, unknown>
type Capture = (event: string, props?: Props) => void

const TOKEN = 'phc_xW4AqiFfnINktDcHGcS5Ugc14GZo0XICN9FhLGLPBJS'

let capture: Capture = () => {}

export function initAnalytics(): void {
  if (!import.meta.env.PROD || import.meta.env.VITE_ANALYTICS_ENABLED === 'false') return
  const queued: Parameters<Capture>[] = []
  capture = (...call) => queued.push(call)
  import('posthog-js').then(
    ({ default: posthog }) => {
      posthog.init(TOKEN, {
        api_host: 'https://us.i.posthog.com',
        persistence: 'localStorage', // no cookies — the footer promise holds
        autocapture: false,
        capture_pageview: false, // manual, on router navigation
        disable_session_recording: true,
      })
      capture = (event, props) => posthog.capture(event, props)
      for (const call of queued) capture(...call)
    },
    () => {
      capture = () => {}
    },
  )
}

export function trackPageview(path: string): void {
  capture('$pageview', { path })
}

export function track(event: string, props?: Props): void {
  capture(event, props)
}
