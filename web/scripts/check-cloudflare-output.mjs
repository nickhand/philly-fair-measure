import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const environment = process.argv[2]
assert.ok(
  environment === 'staging' || environment === 'production',
  'Pass either staging or production to the Cloudflare output checker.',
)

const root = new URL('..', import.meta.url).pathname
const htmlPath = join(root, 'dist', 'index.html')
assert.ok(existsSync(htmlPath), 'The Vite build did not produce dist/index.html.')

const html = readFileSync(htmlPath, 'utf8')
assert.match(html, /(?:src|href)="\/fair-measure\/assets\//)
assert.match(html, /https:\/\/www\.nickhand\.dev\/fair-measure\//)
assert.doesNotMatch(html, /philly-fair-measure\.netlify\.app/)

const config = JSON.parse(readFileSync(join(root, 'wrangler.jsonc'), 'utf8'))
assert.equal(config.account_id, '8ee768918988df338ff5e82a233f9e32')
assert.equal(config.name, 'philly-fair-measure')
assert.equal(config.env.staging.name, 'philly-fair-measure-staging')
assert.equal(config.env.production.name, 'philly-fair-measure-production')
const productionRoutes = config.env.production.routes
assert.deepEqual(productionRoutes, [
  {
    pattern: 'www.nickhand.dev/fair-measure/*',
    zone_name: 'nickhand.dev',
  },
])
assert.equal(config.env[environment].vars.INDEXABLE, environment === 'production' ? 'true' : 'false')
assert.equal(config.assets.not_found_handling, 'none')
assert.equal(config.assets.html_handling, 'none')
assert.ok(existsSync(join(root, 'dist', 'spa.html')), 'Dynamic routes require a separate SPA shell.')

console.log(`Cloudflare ${environment} output is scoped to /fair-measure/ and ready to deploy.`)
