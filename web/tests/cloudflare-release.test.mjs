import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertProductionPage,
  assetUrlFromHtml,
  htmlArtifactForPath,
  PAGE_PATHS,
  pagePathForHtmlArtifact,
  sha256,
  SPA_SHELL,
} from '../scripts/check-cloudflare-release.mjs'
import { resolveAssetRoute } from '../worker/index.mjs'

const appBaseUrl = 'https://www.nickhand.dev/fair-measure'
const html = Buffer.from(
  '<!doctype html><html><head><title>Fair Measure</title>' +
    '<script type="module" src="/fair-measure/assets/index-abc123.js"></script>' +
    '</head><body><div id="app"></div></body></html>',
)

function page(overrides = {}) {
  return {
    status: 200,
    url: `${appBaseUrl}/map`,
    headers: new Headers({
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'public, max-age=0, must-revalidate, no-transform',
      'strict-transport-security': 'max-age=31536000',
      'x-content-type-options': 'nosniff',
      'x-frame-options': 'DENY',
    }),
    body: html,
    ...overrides,
  }
}

test('accepts the exact production shell and its scoped hashed asset', () => {
  assert.match(
    assertProductionPage(page(), {
      appBaseUrl,
      expectedSha256: sha256(html),
      path: '/map',
    }),
    /Fair Measure/,
  )
  assert.equal(
    assetUrlFromHtml(html.toString(), appBaseUrl),
    'https://www.nickhand.dev/fair-measure/assets/index-abc123.js',
  )
})

test('rejects a different artifact, noindex, and an escaped asset', () => {
  assert.throws(
    () => assertProductionPage(page({ url: `${appBaseUrl}/` }), {
      appBaseUrl,
      expectedSha256: sha256(html),
      path: '/map',
    }),
    /redirected/,
  )
  assert.throws(
    () => assertProductionPage(page(), {
      appBaseUrl,
      expectedSha256: '0'.repeat(64),
      path: '/map',
    }),
    /wrong production artifact/,
  )
  assert.throws(
    () => assertProductionPage(page({
      headers: new Headers({
        'content-type': 'text/html',
        'cache-control': 'public, max-age=0, must-revalidate, no-transform',
        'strict-transport-security': 'max-age=31536000',
        'x-content-type-options': 'nosniff',
        'x-frame-options': 'DENY',
        'x-robots-tag': 'noindex',
      }),
    }), {
      appBaseUrl,
      expectedSha256: sha256(html),
      path: '/map',
    }),
    /noindex/,
  )
  assert.throws(
    () => assetUrlFromHtml(
      '<script src="https://example.com/fair-measure/assets/index.js"></script>',
      appBaseUrl,
    ),
    /canonical origin/,
  )
})

const prerendered = new Set([
  'index.html',
  'findings.html',
  'methodology.html',
  'trust.html',
  'appeal.html',
  'report.html',
  'reports/ty-2027.html',
  SPA_SHELL,
  'assets/app-abc123.js',
])

test('expects each page to be served by its own prerendered file or the SPA shell', () => {
  assert.equal(htmlArtifactForPath('/', prerendered), 'index.html')
  assert.equal(htmlArtifactForPath('/findings', prerendered), 'findings.html')
  assert.equal(htmlArtifactForPath('/reports/ty-2027', prerendered), 'reports/ty-2027.html')
  assert.equal(htmlArtifactForPath('/map', prerendered), SPA_SHELL)
  assert.ok(PAGE_PATHS.some((path) => htmlArtifactForPath(path, prerendered) === SPA_SHELL))
})

test('verifies prerendered HTML at the clean URL the worker serves it from', () => {
  assert.equal(pagePathForHtmlArtifact('index.html'), null)
  assert.equal(pagePathForHtmlArtifact(SPA_SHELL), null)
  for (const artifact of ['findings.html', 'report.html', 'reports/ty-2027.html']) {
    const path = pagePathForHtmlArtifact(artifact)
    const route = resolveAssetRoute(`${appBaseUrl}${path}`)
    assert.equal(route.kind, 'asset', `${path} must not redirect`)
    assert.equal(route.url.pathname, `/${artifact}`)
  }
})
