import assert from 'node:assert/strict'
import test from 'node:test'

import worker, { resolveAssetRoute } from '../worker/index.mjs'

test('redirects root and bare Fair Measure requests to the slash path', () => {
  for (const input of ['/', '/fair-measure']) {
    const route = resolveAssetRoute(`https://example.workers.dev${input}?source=test`)
    assert.deepEqual(
      { kind: route.kind, status: route.status, url: route.url.href },
      {
        kind: 'redirect',
        status: 301,
        url: 'https://example.workers.dev/fair-measure/?source=test',
      },
    )
  }
})

test('maps the public subpath to the root of the static-assets binding', () => {
  const route = resolveAssetRoute(
    'https://www.nickhand.dev/fair-measure/assets/index-abc.js?version=1',
  )
  assert.equal(route.kind, 'asset')
  assert.equal(route.url.href, 'https://www.nickhand.dev/assets/index-abc.js?version=1')
  assert.equal(resolveAssetRoute('https://www.nickhand.dev/fair-measured'), null)
})

test('resolves generated HTML and canonical redirects without losing the public prefix', () => {
  for (const [path, asset] of [['/', '/index.html'], ['/appeal', '/appeal.html'], ['/reports/ty-2027', '/reports/ty-2027.html']]) {
    const route = resolveAssetRoute(`https://example.com/fair-measure${path}?acct=123456789`)
    assert.equal(route.url.pathname, asset)
    assert.equal(route.url.search, '?acct=123456789')
  }
  for (const path of ['/appeal/', '/appeal.html']) {
    const route = resolveAssetRoute(`https://example.com/fair-measure${path}?acct=123456789`)
    assert.equal(route.kind, 'redirect')
    assert.equal(route.url.href, 'https://example.com/fair-measure/appeal?acct=123456789')
  }
  assert.equal(resolveAssetRoute('https://example.com/fair-measure/spa.html'), null)
})

test('uses the empty SPA shell for dynamic routes and returns 404 for unknown pages', async () => {
  for (const [path, status, noindex] of [
    ['/map', 200, false], ['/property/123456789', 200, false],
    ['/admin', 200, true], ['/leaderboards', 200, true], ['/missing-page', 404, true],
  ]) {
    const requests = []
    const assets = { fetch: async (request) => {
      const pathname = new URL(request.url).pathname
      requests.push(pathname)
      return pathname === '/spa.html'
        ? new Response('<div id="app"></div>', { headers: { 'Content-Type': 'text/html' } })
        : new Response('Not found', { status: 404 })
    } }
    const response = await worker.fetch(new Request(`https://www.nickhand.dev/fair-measure${path}`),
      { ASSETS: assets, INDEXABLE: 'true' })
    assert.equal(response.status, status, path)
    assert.deepEqual(requests, [`${path}.html`, '/spa.html'])
    assert.equal(await response.text(), '<div id="app"></div>')
    assert.equal(response.headers.get('X-Robots-Tag'), noindex ? 'noindex, nofollow' : null)
  }
})

test('serves a generated page without falling back to the SPA shell', async () => {
  const requests = []
  const assets = { fetch: async (request) => {
    requests.push(new URL(request.url).pathname)
    return new Response('<h1>Appeal your assessment</h1>', { headers: { 'Content-Type': 'text/html' } })
  } }
  const response = await worker.fetch(new Request('https://www.nickhand.dev/fair-measure/appeal'),
    { ASSETS: assets, INDEXABLE: 'true' })
  assert.deepEqual(requests, ['/appeal.html'])
  assert.equal(response.status, 200)
  assert.match(await response.text(), /Appeal your assessment/)
})

test('serves assets with the public security, cache, and crawler policy', async () => {
  let assetRequest
  const assets = {
    fetch: async (request) => {
      assetRequest = request
      return new Response('console.log("fair")', {
        headers: { 'Content-Type': 'application/javascript' },
      })
    },
  }

  const response = await worker.fetch(
    new Request('https://philly-fair-measure-staging.example.workers.dev/fair-measure/assets/app.js'),
    { ASSETS: assets, INDEXABLE: 'false' },
  )

  assert.equal(new URL(assetRequest.url).pathname, '/assets/app.js')
  assert.equal(response.headers.get('X-Robots-Tag'), 'noindex, nofollow')
  assert.equal(response.headers.get('Strict-Transport-Security'), null)
  assert.equal(response.headers.get('X-Frame-Options'), 'DENY')
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=31536000, immutable')
})

test('production HTML is revalidated and receives HSTS', async () => {
  const assets = {
    fetch: async () => new Response('<main>Fair Measure</main>', {
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    }),
  }
  const response = await worker.fetch(
    new Request('https://www.nickhand.dev/fair-measure/map'),
    { ASSETS: assets, INDEXABLE: 'true' },
  )

  assert.equal(response.headers.get('X-Robots-Tag'), null)
  assert.equal(response.headers.get('Strict-Transport-Security'), 'max-age=31536000')
  assert.equal(
    response.headers.get('Cache-Control'),
    'public, max-age=0, must-revalidate, no-transform',
  )
})

test('rejects SPA fallback HTML for missing file requests', async () => {
  const assets = {
    fetch: async () => new Response('<main>SPA fallback</main>', {
      headers: { 'Content-Type': 'text/html' },
    }),
  }
  const response = await worker.fetch(
    new Request('https://example.workers.dev/fair-measure/assets/not-real.js'),
    { ASSETS: assets, INDEXABLE: 'false' },
  )

  assert.equal(response.status, 404)
  assert.equal(response.headers.get('Cache-Control'), null)
  assert.equal(await response.text(), 'Not found')
})
