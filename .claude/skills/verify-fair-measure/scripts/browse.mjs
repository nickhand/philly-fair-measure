#!/usr/bin/env node
// Drive one page journey in headless system Chrome and save what a visitor sees.
// Run from the checkout root; Playwright loads from its web/node_modules.
//
//   node browse.mjs <out-dir> <name> <url> [step ...]
//
// Steps run in order; every locator is an ARIA role plus accessible name (substring match):
//   fill:<role>:<name>=<text>   type into a field
//   click:<role>:<name>         click it
//   wait:<role>:<name>          wait until it is visible
//   text:<text>                 wait until this text is visible
//   gone:<text>                 wait until this text is hidden (a loading message)
//   snap:<label>                save <name>-<label>.png and .aria.txt
// The final state is always saved as <name>-final. Every /api/ response the page made, console
// errors, page errors, failed requests and HTTP >= 400 responses go to <name>.log.json.
// Exits 1 if a step fails.
import { mkdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const require = createRequire(join(process.cwd(), 'web', 'package.json'))
const { chromium } = require('playwright')

const [outDir, name, url, ...steps] = process.argv.slice(2)
if (!outDir || !name || !url) {
  console.error('usage: node browse.mjs <out-dir> <name> <url> [step ...]')
  process.exit(2)
}
mkdirSync(outDir, { recursive: true })

const problems = []
const done = []
const api = []
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
page.on('console', (msg) => msg.type() === 'error' && problems.push(`console: ${msg.text()}`))
page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`))
page.on('requestfailed', (req) => problems.push(`failed: ${req.url()} ${req.failure()?.errorText}`))
page.on('response', (res) => {
  if (res.url().includes('/api/')) api.push(`${res.status()} ${res.url()}`)
  if (res.status() >= 400) problems.push(`http ${res.status()}: ${res.url()}`)
})

async function snap(label) {
  const base = join(outDir, `${name}-${label}`)
  await page.screenshot({ path: `${base}.png`, fullPage: true })
  writeFileSync(`${base}.aria.txt`, `${page.url()}\n${await page.locator('body').ariaSnapshot()}\n`)
  done.push(`snap ${base}.png`)
}

function locate(spec) {
  const at = spec.indexOf(':')
  return page.getByRole(spec.slice(0, at), { name: spec.slice(at + 1) }).first()
}

let exitCode = 0
try {
  const response = await page.goto(url, { waitUntil: 'domcontentloaded' })
  done.push(`goto ${url} -> ${response?.status()}`)
  for (const step of steps) {
    const at = step.indexOf(':')
    const [action, arg] = [step.slice(0, at), step.slice(at + 1)]
    if (action === 'fill') {
      const eq = arg.indexOf('=')
      await locate(arg.slice(0, eq)).fill(arg.slice(eq + 1))
    } else if (action === 'click') {
      await locate(arg).click()
    } else if (action === 'wait') {
      await locate(arg).waitFor({ timeout: 30_000 })
    } else if (action === 'text') {
      await page.getByText(arg).first().waitFor({ timeout: 30_000 })
    } else if (action === 'gone') {
      await page.getByText(arg).first().waitFor({ state: 'hidden', timeout: 30_000 })
    } else if (action === 'snap') {
      await snap(arg)
      continue
    } else {
      throw new Error(`unknown step ${step}`)
    }
    done.push(step)
  }
  await snap('final')
} catch (err) {
  exitCode = 1
  problems.push(`step failed after [${done.at(-1) ?? 'start'}]: ${err.message.split('\n')[0]}`)
  await snap('failed').catch(() => {})
} finally {
  await browser.close()
}
writeFileSync(join(outDir, `${name}.log.json`), `${JSON.stringify({ url, steps, done, api, problems }, null, 2)}\n`)
for (const line of done) console.log(`  ok  ${line}`)
for (const line of api) console.log(`  api ${line}`)
for (const line of problems) console.log(`  !!  ${line}`)
console.log(`${exitCode ? 'FAILED' : 'passed'}: ${name} (${problems.length} problems logged)`)
process.exit(exitCode)
