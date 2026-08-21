import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertProductionPage,
  assetUrlFromHtml,
  sha256,
} from '../scripts/check-cloudflare-release.mjs'

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
      expectedIndexSha256: sha256(html),
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
      expectedIndexSha256: sha256(html),
      path: '/map',
    }),
    /redirected/,
  )
  assert.throws(
    () => assertProductionPage(page(), {
      appBaseUrl,
      expectedIndexSha256: '0'.repeat(64),
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
      expectedIndexSha256: sha256(html),
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
