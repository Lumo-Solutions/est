import { describe, expect, it } from 'vitest'
import { confidenceBand, confidenceColor } from './confidence'

describe('confidenceBand', () => {
  it('bands >= 0.8 as high', () => {
    expect(confidenceBand(0.8)).toBe('high')
    expect(confidenceBand(1)).toBe('high')
  })
  it('bands 0.5-0.79 as medium', () => {
    expect(confidenceBand(0.5)).toBe('medium')
    expect(confidenceBand(0.79)).toBe('medium')
  })
  it('bands below 0.5 as low', () => {
    expect(confidenceBand(0.49)).toBe('low')
    expect(confidenceBand(0)).toBe('low')
  })
})

describe('confidenceColor', () => {
  it('maps each band to a distinct color', () => {
    const colors = new Set([confidenceColor(1), confidenceColor(0.6), confidenceColor(0.1)])
    expect(colors.size).toBe(3)
  })
})
