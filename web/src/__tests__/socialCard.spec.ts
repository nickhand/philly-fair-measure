import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'public')
const read = (name: string) => readFileSync(join(PUBLIC, name))
const svg = read('social-card.svg').toString('utf8')
const text = [...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1]).join(' ')

describe('social card', () => {
  it('keeps the independence disclaimer', () => {
    expect(text).toContain('not a City of Philadelphia product')
  })

  it('makes no "no analytics" promise, since production runs PostHog', () => {
    expect(text).not.toMatch(/no analytics/i)
  })

  it('ships a PNG at the SVG size', () => {
    const png = read('social-card.png')
    const [, width, height] = svg.match(/<svg[^>]* width="(\d+)" height="(\d+)"/) ?? []
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([Number(width), Number(height)])
  })
})
