/**
 * WCAG 2.1 AA for the site's text colors (docs/design-brief.md): 4.5:1 for small
 * text. Captions, chart labels and the legal disclaimers are 11.5–12.5 px, so every
 * text token and every SVG <text> fill must clear 4.5:1 on the backgrounds text sits
 * on: white cards and the paper page.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Map as MLMap } from 'maplibre-gl'
import { describe, expect, it } from 'vitest'
import { applyFairMeasurePaint } from '@/map/fairMeasureMapStyle'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const css = readFileSync(join(SRC, 'assets', 'main.css'), 'utf8')
const token = (name: string) => css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-f]{6})`, 'i'))![1]!

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi! + 0.05) / (lo! + 0.05)
}

const BACKGROUNDS = { white: '#ffffff', paper: token('paper') }

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    return e.isDirectory() ? walk(p) : [p]
  })
}

describe('text contrast', () => {
  it.each(['ink', 'body', 'muted', 'faint'])('--color-%s clears 4.5:1 on white and paper', (name) => {
    const color = token(name)
    for (const [bg, hex] of Object.entries(BACKGROUNDS)) {
      expect(contrast(color, hex), `${name} ${color} on ${bg} ${hex}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('every SVG chart label clears 4.5:1 on white', () => {
    const offenders: string[] = []
    for (const file of walk(SRC).filter((f) => f.endsWith('.vue'))) {
      for (const tag of readFileSync(file, 'utf8').match(/<text\b[^>]*>/g) ?? []) {
        for (const [hex] of tag.matchAll(/#[0-9a-f]{6}\b/gi)) {
          const ratio = contrast(hex, BACKGROUNDS.white)
          if (ratio < 4.5) offenders.push(`${relative(SRC, file)}: <text> fill ${hex} is ${ratio.toFixed(2)}:1`)
        }
      }
    }
    expect(offenders, `\n${offenders.join('\n')}\n`).toEqual([])
  })

  it('basemap labels clear 4.5:1 on their halo', () => {
    const paint: Record<string, string> = {}
    const map = {
      getStyle: () => ({ layers: [{ id: 'label_city', type: 'symbol' }] }),
      setPaintProperty: (_id: string, property: string, value: string) => {
        paint[property] = value
      },
    } as unknown as MLMap
    applyFairMeasurePaint(map)
    const ratio = contrast(paint['text-color']!, paint['text-halo-color']!)
    expect(ratio, `${paint['text-color']} on ${paint['text-halo-color']}`).toBeGreaterThanOrEqual(4.5)
  })
})
