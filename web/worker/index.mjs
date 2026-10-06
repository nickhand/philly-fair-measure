const BASE_PATH = '/fair-measure'

function addResponseHeaders(response, requestUrl, indexable) {
  const headers = new Headers(response.headers)
  headers.set('X-Content-Type-Options', 'nosniff')
  headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
  headers.set('Permissions-Policy', 'camera=(), geolocation=(), microphone=()')
  headers.set('X-Frame-Options', 'DENY')

  if (new URL(requestUrl).hostname.endsWith('nickhand.dev')) {
    headers.set('Strict-Transport-Security', 'max-age=31536000')
  }

  if (!indexable) {
    headers.set('X-Robots-Tag', 'noindex, nofollow')
  }

  const requestPath = new URL(requestUrl).pathname
  const contentType = headers.get('Content-Type') ?? ''
  if (
    response.ok &&
    requestPath.startsWith(`${BASE_PATH}/assets/`) &&
    !contentType.includes('text/html')
  ) {
    headers.set('Cache-Control', 'public, max-age=31536000, immutable')
  } else if (contentType.includes('text/html')) {
    headers.set('Cache-Control', 'public, max-age=0, must-revalidate, no-transform')
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}

export function resolveAssetRoute(requestUrl) {
  const url = new URL(requestUrl)

  if (url.pathname === '/' || url.pathname === BASE_PATH) {
    const target = new URL(`${BASE_PATH}/`, url)
    target.search = url.search
    return { kind: 'redirect', status: 301, url: target }
  }

  if (!url.pathname.startsWith(`${BASE_PATH}/`)) return null

  const assetUrl = new URL(url)
  const path = url.pathname.slice(BASE_PATH.length)
  // This is an internal fallback, not an indexable page.
  if (path === '/spa.html') return null
  if (path !== '/' && (path.endsWith('/') || path.endsWith('.html'))) {
    const target = new URL(url)
    const clean = path.replace(/\/index\.html$/, '/').replace(/\.html$/, '').replace(/\/$/, '')
    target.pathname = `${BASE_PATH}${clean || '/'}`
    return { kind: 'redirect', status: 301, url: target }
  }
  assetUrl.pathname = path === '/' ? '/index.html' : /\/[^/]+\.[a-z0-9]+$/i.test(path)
    ? path
    : `${path}.html`
  return { kind: 'asset', url: assetUrl }
}

function isFileRequest(requestUrl) {
  const pathname = new URL(requestUrl).pathname
  return pathname.startsWith(`${BASE_PATH}/assets/`) || /\/[^/]+\.[a-z0-9]+$/i.test(pathname)
}

export default {
  async fetch(request, env) {
    const route = resolveAssetRoute(request.url)
    const indexable = env.INDEXABLE === 'true'

    if (!route) {
      return addResponseHeaders(new Response('Not found', { status: 404 }), request.url, indexable)
    }

    if (route.kind === 'redirect') {
      return addResponseHeaders(
        Response.redirect(route.url, route.status),
        request.url,
        indexable,
      )
    }

    let response = await env.ASSETS.fetch(new Request(route.url, request))
    if (response.status === 404 && !isFileRequest(request.url)) {
      const shell = new URL('/spa.html', request.url)
      const fallback = await env.ASSETS.fetch(new Request(shell, request))
      const path = new URL(request.url).pathname.slice(BASE_PATH.length)
      const clientRoute = ['/map', '/admin', '/leaderboards'].includes(path) ||
        /^\/property\/[^/]+$/.test(path)
      response = new Response(fallback.body, {
        status: fallback.ok && clientRoute ? 200 : 404,
        headers: fallback.headers,
      })
      if (!clientRoute || path === '/admin' || path === '/leaderboards') {
        response.headers.set('X-Robots-Tag', 'noindex, nofollow')
      }
    }
    if (
      isFileRequest(request.url) &&
      (response.headers.get('Content-Type') ?? '').includes('text/html')
    ) {
      return addResponseHeaders(new Response('Not found', { status: 404 }), request.url, indexable)
    }
    return addResponseHeaders(response, request.url, indexable)
  },
}
