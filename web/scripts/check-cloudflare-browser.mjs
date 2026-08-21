#!/usr/bin/env node

import assert from 'node:assert/strict'

import { chromium } from 'playwright'

const appBaseUrl = process.argv[2]?.replace(/\/$/, '')
assert.match(appBaseUrl ?? '', /^https:\/\/[^/?#]+\/fair-measure$/i, 'pass the canonical Fair Measure base URL')

const appOrigin = new URL(appBaseUrl).origin
const apiOrigin = 'https://fair-measure-api.fly.dev'
const failures = []

function observedOrigin(rawUrl) {
  try {
    const origin = new URL(rawUrl).origin
    return origin === appOrigin || origin === apiOrigin
  } catch {
    return false
  }
}

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`))
  page.on('requestfailed', (request) => {
    const url = request.url()
    if (observedOrigin(url)) {
      failures.push(`request failed: ${url} (${request.failure()?.errorText ?? 'unknown'})`)
    }
  })
  page.on('response', (response) => {
    const url = response.url()
    if (observedOrigin(url) && response.status() >= 400) {
      failures.push(`response ${response.status()}: ${url}`)
    }
  })

  const appStatsResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.origin === apiOrigin && url.pathname === '/api/stats'
  })
  const homeResponse = await page.goto(`${appBaseUrl}/`, { waitUntil: 'domcontentloaded' })
  assert.equal(homeResponse?.status(), 200)
  assert.equal(new URL(page.url()).pathname, '/fair-measure/')
  await page.getByRole('heading', { name: 'Is your home’s assessment fair?', exact: true }).waitFor()
  const statsResponse = await appStatsResponse
  assert.equal(statsResponse.status(), 200)
  assert.match(statsResponse.headers()['content-type'] ?? '', /application\/json/i)
  const stats = await statsResponse.json()
  assert.ok(Number.isInteger(stats.properties) && stats.properties > 0)
  await page.waitForFunction(
    () => document.querySelector('[role="status"][aria-label="Loading"]') === null,
    undefined,
    { timeout: 15_000 },
  )
  assert.match(await page.title(), /Fair Measure/)

  const mapResponse = await page.goto(`${appBaseUrl}/map`, { waitUntil: 'domcontentloaded' })
  assert.equal(mapResponse?.status(), 200)
  assert.equal(new URL(page.url()).pathname, '/fair-measure/map')
  await page.getByRole('heading', { name: 'Assessment map of Philadelphia', exact: true }).waitFor()
  await page.getByRole('region', { name: /Map of Philadelphia homes/ }).waitFor()

  const reportResponse = await page.goto(`${appBaseUrl}/reports/ty-2027`, {
    waitUntil: 'domcontentloaded',
  })
  assert.equal(reportResponse?.status(), 200)
  assert.equal(new URL(page.url()).pathname, '/fair-measure/reports/ty-2027')
  await page.locator('h1').waitFor()
  assert.ok((await page.locator('h1').innerText()).trim().length > 10)

  const health = await page.evaluate(async (url) => {
    const response = await fetch(url, { headers: { accept: 'application/json' } })
    return { ok: response.ok, body: await response.json() }
  }, `${apiOrigin}/health`)
  assert.equal(health.ok, true)
  assert.equal(health.body.status, 'ok')
  assert.ok(Number.isInteger(health.body.rows) && health.body.rows > 0)
  assert.deepEqual(failures, [])

  console.log('Cloudflare browser smoke passed: home, map, annual report, and API health hydrated.')
} finally {
  await browser.close()
}
