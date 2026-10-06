import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dist = new URL('../dist/', import.meta.url)
const stats = JSON.parse(readFileSync(new URL('../src/data/siteStats.json', import.meta.url), 'utf8'))
const reportPath = `/reports/ty-${stats.annual_report.tax_year}`
const paths = ['/', '/findings', '/methodology', '/trust', '/appeal', reportPath, '/report']
const titles = new Set()

for (const path of paths) {
  const file = path === '/' ? 'index.html' : `${path.slice(1)}.html`
  const html = readFileSync(new URL(file, dist), 'utf8')
  const { document } = new JSDOM(html).window
  const canonicalPath = path === '/report' ? reportPath : path
  const canonical = `https://www.nickhand.dev/fair-measure${canonicalPath}`
  assert.equal(document.querySelector('#app')?.getAttribute('data-server-rendered'), 'true', file)
  assert.ok(document.querySelector('main h1')?.textContent.trim(), `${file}: missing rendered heading`)
  assert.ok(document.querySelector('main')?.textContent.length > 300, `${file}: empty page shell`)
  assert.equal(document.querySelectorAll('title').length, 1, file)
  assert.equal(document.querySelectorAll('link[rel="canonical"]').length, 1, file)
  assert.equal(document.querySelector('link[rel="canonical"]').getAttribute('href'), canonical, file)
  assert.equal(document.querySelectorAll('meta[name="description"]').length, 1, file)
  assert.equal(document.querySelectorAll('meta[name="robots"]').length, 1, file)
  const description = document.querySelector('meta[name="description"]').getAttribute('content')
  assert.ok(description.length > 50, file)
  for (const [selector, content] of [
    ['meta[property="og:title"]', document.title],
    ['meta[name="twitter:title"]', document.title],
    ['meta[property="og:description"]', description],
    ['meta[name="twitter:description"]', description],
    ['meta[property="og:url"]', canonical],
    ['meta[name="twitter:url"]', canonical],
  ]) {
    assert.equal(document.querySelectorAll(selector).length, 1, `${file}: ${selector}`)
    assert.equal(document.querySelector(selector).getAttribute('content'), content, `${file}: ${selector}`)
  }
  if (path !== '/report') titles.add(document.title)
  // The clock and saved banner dismissal must never be captured at build time.
  assert.equal(document.querySelector('[aria-label="Assessment timing notice"]'), null, file)
  if (path === '/appeal') {
    const text = document.querySelector('main').textContent.replace(/\s+/g, ' ')
    assert.match(text, /First Level Review deadline/)
    assert.doesNotMatch(text, /is due by|was due by|deadlines have passed|Ask OPA for a|file a formal appeal/)
    assert.equal(document.querySelector('#acct').getAttribute('value') ?? '', '')
  }
  if (path === '/') {
    const text = document.querySelector('main').textContent
    assert.ok(text.includes(stats.screen.properties.toLocaleString('en-US')))
    assert.equal(document.querySelector('[aria-label="Loading"]'), null)
  }
}
assert.equal(titles.size, 6, 'Informational pages must have distinct titles')
const shell = new JSDOM(readFileSync(new URL('spa.html', dist), 'utf8')).window.document
assert.equal(shell.querySelector('#app').innerHTML, '', 'Dynamic routes need an empty, non-hydrating shell')
assert.equal(shell.querySelector('link[rel="canonical"]'), null, 'Do not pin Home as dynamic routes’ canonical')
for (const path of ['map.html', 'admin.html', 'leaderboards.html', 'property']) {
  assert.equal(existsSync(new URL(path, dist)), false, `Unexpected pre-rendered dynamic route: ${path}`)
}
console.log('Verified 6 pre-rendered pages, the report alias, per-page metadata, neutral deadlines, and SPA fallback.')
