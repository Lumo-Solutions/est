import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// docs/figma-implementation-plan.md 1.6 -- the AA contract for the Figma
// token set. Reads the real @theme from index.css so a future edit to a
// token can't silently drop below the threshold the axe suite depends on.
const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

function token(name: string): string {
  const m = css.match(new RegExp(`--color-${name}:\\s*(#[0-9A-Fa-f]{6})`))
  if (!m) throw new Error(`token --color-${name} not found in index.css`)
  return m[1]
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const WHITE = '#FFFFFF'
const TEXT_MIN = 4.5
const NON_TEXT_MIN = 3

describe('token contrast (WCAG AA)', () => {
  const canvas = token('canvas')

  it.each(['brand', 'brand-hover', 'accent', 'ink', 'ink-2', 'ink-title', 'muted'])(
    'text token %s is >= 4.5:1 on white and on canvas',
    (name) => {
      expect(ratio(token(name), WHITE)).toBeGreaterThanOrEqual(TEXT_MIN)
      expect(ratio(token(name), canvas)).toBeGreaterThanOrEqual(TEXT_MIN)
    },
  )

  it('white text on brand and brand-hover buttons is >= 4.5:1', () => {
    expect(ratio(WHITE, token('brand'))).toBeGreaterThanOrEqual(TEXT_MIN)
    expect(ratio(WHITE, token('brand-hover'))).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  it('outline (input/control boundary) is >= 3:1 on white and on canvas', () => {
    expect(ratio(token('outline'), WHITE)).toBeGreaterThanOrEqual(NON_TEXT_MIN)
    expect(ratio(token('outline'), canvas)).toBeGreaterThanOrEqual(NON_TEXT_MIN)
  })

  it('fill-only tokens are documented as unsafe for text (guards against accidental promotion)', () => {
    // If one of these ever passes 4.5:1, the "fill only" comment in index.css is stale.
    for (const name of ['negative-fill', 'accent-teal', 'success']) {
      expect(ratio(token(name), WHITE)).toBeLessThan(TEXT_MIN)
    }
  })
})
