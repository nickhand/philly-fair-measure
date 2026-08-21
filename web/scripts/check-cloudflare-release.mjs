#!/usr/bin/env node

import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readdir, readFile } from 'node:fs/promises'
import { join, relative, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

export const PAGE_PATHS = [
  '/',
  '/map',
  '/reports/ty-2027',
  '/findings',
  '/methodology',
  '/trust',
  '/appeal',
]

const MAX_RESPONSE_BYTES = 5 * 1024 * 1024
const REQUIRED_HEADERS = {
  'strict-transport-security': /(?:^|\s)max-age=31536000(?:[;\s]|$)/i,
  'x-content-type-options': /^nosniff$/i,
  'x-frame-options': /^DENY$/i,
}
const ASSET_PATTERN = /(?:src|href)=["']([^"']*\/assets\/[^"']+\.(?:css|js))(?:\?[^"']*)?["']/i

export function sha256(body) {
  return createHash('sha256').update(body).digest('hex')
}

function assertCanonicalUrl(url, appBaseUrl, label) {
  const actual = new URL(url)
  const base = new URL(`${appBaseUrl.replace(/\/$/, '')}/`)
  assert.equal(actual.origin, base.origin, `${label} escaped the canonical origin`)
  assert.ok(
    actual.pathname === base.pathname.slice(0, -1) || actual.pathname.startsWith(base.pathname),
    `${label} escaped the canonical application path`,
  )
}

export function assertProductionPage(page, { appBaseUrl, expectedIndexSha256, path }) {
  assert.equal(page.status, 200, `production page returned ${page.status}: ${path}`)
  assertCanonicalUrl(page.url, appBaseUrl, `production page ${path}`)
  const basePath = new URL(`${appBaseUrl.replace(/\/$/, '')}/`).pathname
  const expectedPath = path === '/' ? basePath : `${basePath}${path.replace(/^\//, '')}`
  assert.equal(new URL(page.url).pathname, expectedPath, `production page redirected: ${path}`)
  assert.match(page.headers.get('content-type') ?? '', /text\/html/i, `page is not HTML: ${path}`)
  const html = page.body.toString('utf8')
  assert.match(html, /<!doctype html|<html(?:\s|>)/i, `page has no HTML document: ${path}`)
  assert.match(html, /<title>[^<]+/i, `page has no title: ${path}`)
  assert.doesNotMatch(html, /<meta[^>]+name=["']robots["'][^>]+noindex/i, `page contains noindex: ${path}`)
  assert.doesNotMatch(page.headers.get('x-robots-tag') ?? '', /noindex/i, `response contains noindex: ${path}`)
  for (const [name, pattern] of Object.entries(REQUIRED_HEADERS)) {
    assert.match(page.headers.get(name) ?? '', pattern, `invalid ${name}: ${path}`)
  }
  assert.match(
    page.headers.get('cache-control') ?? '',
    /(?:^|,\s*)public(?:,|$).*max-age=0.*must-revalidate/i,
    `invalid HTML cache policy: ${path}`,
  )
  assert.match(
    page.headers.get('cache-control') ?? '',
    /(?:^|,\s*)no-transform(?:,|$)/i,
    `HTML permits edge transformation: ${path}`,
  )
  assert.equal(sha256(page.body), expectedIndexSha256, `wrong production artifact: ${path}`)
  return html
}

export function assetUrlFromHtml(html, appBaseUrl) {
  const match = ASSET_PATTERN.exec(html)
  assert.ok(match, 'homepage does not reference a hashed JS or CSS asset')
  const assetUrl = new URL(match[1], `${appBaseUrl.replace(/\/$/, '')}/`)
  assertCanonicalUrl(assetUrl.href, appBaseUrl, 'homepage asset')
  const basePath = new URL(`${appBaseUrl.replace(/\/$/, '')}/`).pathname
  assert.ok(assetUrl.pathname.startsWith(`${basePath}assets/`), 'homepage asset escaped /fair-measure/assets/')
  return assetUrl.href
}

async function fetchBounded(url) {
  const response = await fetch(url, {
    headers: {
      accept: 'text/html,*/*;q=0.8',
      'cache-control': 'no-cache',
      'user-agent': 'philly-fair-measure-release-check/1',
    },
    signal: AbortSignal.timeout(10_000),
  })
  const declaredLength = Number(response.headers.get('content-length') ?? 0)
  assert.ok(!declaredLength || declaredLength <= MAX_RESPONSE_BYTES, `response is too large: ${url}`)
  const body = Buffer.from(await response.arrayBuffer())
  assert.ok(body.length <= MAX_RESPONSE_BYTES, `response is too large: ${url}`)
  return { status: response.status, url: response.url, headers: response.headers, body }
}

async function artifactFiles(root) {
  const files = []
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true })
    for (const entry of entries) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await visit(path)
      else if (entry.isFile()) files.push(path)
      else throw new Error(`release artifact contains a non-file entry: ${path}`)
    }
  }
  await visit(root)
  return files.sort()
}

async function requireExactArtifacts({ appBaseUrl, artifactDirectory, expectedIndexSha256 }) {
  const files = await artifactFiles(artifactDirectory)
  assert.ok(files.length >= 2, 'release artifact does not contain static assets')
  for (const file of files) {
    const artifactPath = relative(artifactDirectory, file)
    const expectedBody = await readFile(file)
    if (artifactPath === 'index.html') {
      assert.equal(sha256(expectedBody), expectedIndexSha256, 'artifact index digest changed')
      continue
    }
    const encodedPath = artifactPath.split(sep).map(encodeURIComponent).join('/')
    const expectedUrl = `${appBaseUrl.replace(/\/$/, '')}/${encodedPath}`
    const live = await fetchBounded(expectedUrl)
    assert.equal(live.status, 200, `artifact returned ${live.status}: ${artifactPath}`)
    assert.equal(live.url, expectedUrl, `artifact redirected: ${artifactPath}`)
    assert.equal(sha256(live.body), sha256(expectedBody), `artifact digest mismatch: ${artifactPath}`)
    if (!artifactPath.endsWith('.html')) {
      assert.doesNotMatch(
        live.headers.get('content-type') ?? '',
        /text\/html/i,
        `artifact returned SPA HTML: ${artifactPath}`,
      )
    }
  }
  return files.length
}

async function waitForPage({ url, appBaseUrl, expectedIndexSha256, path, attempts, retryDelayMs }) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const page = await fetchBounded(`${url}${url.includes('?') ? '&' : '?'}deployment-audit=${Date.now()}`)
      return { page, html: assertProductionPage(page, { appBaseUrl, expectedIndexSha256, path }) }
    } catch (error) {
      lastError = error
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, retryDelayMs))
    }
  }
  throw new Error(`exact production page was not live after ${attempts} attempts: ${path}`, { cause: lastError })
}

export async function checkCloudflareRelease({
  appBaseUrl,
  expectedIndexSha256,
  artifactDirectory,
  attempts = 30,
  retryDelayMs = 10_000,
}) {
  assert.match(appBaseUrl, /^https:\/\/[^/?#]+\/[^?#]+$/i, 'app base URL must be an HTTPS origin and path')
  assert.match(expectedIndexSha256, /^[0-9a-f]{64}$/, 'expected index SHA-256 must be lowercase hexadecimal')
  assert.ok(artifactDirectory, 'artifact directory is required')
  assert.ok(Number.isInteger(attempts) && attempts >= 1, 'attempts must be a positive integer')
  assert.ok(Number.isInteger(retryDelayMs) && retryDelayMs >= 0, 'retry delay must be nonnegative')

  const base = appBaseUrl.replace(/\/$/, '')
  let homepageHtml = ''
  for (const path of PAGE_PATHS) {
    const { html } = await waitForPage({
      url: `${base}${path}`,
      appBaseUrl: base,
      expectedIndexSha256,
      path,
      attempts,
      retryDelayMs,
    })
    if (path === '/') homepageHtml = html
  }

  const assetUrl = assetUrlFromHtml(homepageHtml, base)
  const asset = await fetchBounded(assetUrl)
  assert.equal(asset.status, 200, `homepage asset returned ${asset.status}`)
  assert.equal(asset.url, assetUrl, 'homepage asset redirected')
  assert.ok(asset.body.length > 0, 'homepage asset is empty')
  assert.match(asset.headers.get('cache-control') ?? '', /immutable/i, 'homepage asset is not immutable')
  const artifactCount = await requireExactArtifacts({
    appBaseUrl: base,
    artifactDirectory,
    expectedIndexSha256,
  })
  return { assetUrl, artifactCount }
}

function parseArguments(argv) {
  const values = new Map()
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]
    const value = argv[index + 1]
    assert.ok(flag?.startsWith('--') && value !== undefined, `invalid argument: ${flag ?? ''}`)
    values.set(flag.slice(2), value)
  }
  return {
    appBaseUrl: values.get('app-base-url'),
    expectedIndexSha256: values.get('expected-index-sha256'),
    artifactDirectory: values.get('artifact-directory'),
    attempts: values.has('attempts') ? Number(values.get('attempts')) : 30,
    retryDelayMs: values.has('retry-delay-ms') ? Number(values.get('retry-delay-ms')) : 10_000,
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const options = parseArguments(process.argv.slice(2))
    assert.ok(options.appBaseUrl, '--app-base-url is required')
    assert.ok(options.expectedIndexSha256, '--expected-index-sha256 is required')
    const result = await checkCloudflareRelease(options)
    console.log(
      `Cloudflare release check passed: pages=${PAGE_PATHS.length} artifacts=${result.artifactCount} asset=${result.assetUrl}`,
    )
  } catch (error) {
    const messages = []
    let current = error
    while (current instanceof Error && !messages.includes(current.message)) {
      messages.push(current.message)
      current = current.cause
    }
    console.error(`Cloudflare release check failed: ${messages.join(' <- ') || String(error)}`)
    process.exitCode = 1
  }
}
