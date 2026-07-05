/** Anonymous usage analytics (PostHog), configured for a civic-trust site:
 * no cookies (localStorage persistence only), no autocapture, no session
 * recording — only the explicit events below and manual pageviews. Inits in
 * production builds only so dev sessions don't pollute the numbers. The token
 * is a publishable client key. */
import posthog from 'posthog-js'

const TOKEN = 'phc_xW4AqiFfnINktDcHGcS5Ugc14GZo0XICN9FhLGLPBJS'

let ready = false

export function initAnalytics(): void {
  if (!import.meta.env.PROD) return
  posthog.init(TOKEN, {
    api_host: 'https://us.i.posthog.com',
    persistence: 'localStorage', // no cookies — the footer promise holds
    autocapture: false,
    capture_pageview: false, // manual, on router navigation
    disable_session_recording: true,
  })
  ready = true
}

export function trackPageview(path: string): void {
  if (ready) posthog.capture('$pageview', { path })
}

export function track(event: string, props?: Record<string, unknown>): void {
  if (ready) posthog.capture(event, props)
}
