import { describe, expect, it } from 'vitest'
import { confidenceTone, flagLabel, formatConfidence, isSuperseded, splitIntoBatches, statusTone } from './lib'
import type { TenderDocument } from './types'

const MB = 1024 * 1024

describe('tender intake lib', () => {
  it('confidence tone and format', () => {
    expect(confidenceTone(0.85)).toBe('success')
    expect(confidenceTone(0.84)).toBe('warning')
    expect(confidenceTone(0.5)).toBe('warning')
    expect(confidenceTone(0.49)).toBe('danger')
    expect(formatConfidence(0.85)).toBe('85%')
    expect(formatConfidence(null)).toBe('--')
  })

  it('flag labels are plain English', () => {
    expect(flagLabel('low_confidence')).toBe('Low confidence')
    expect(flagLabel('convert_to_dxf')).toBe('Convert to DXF')
    expect(flagLabel('some_new_flag')).toBe('some new flag')
  })

  it('status tones', () => {
    expect(statusTone('proposed')).toBe('warning')
    expect(statusTone('confirmed')).toBe('info')
    expect(statusTone('routed')).toBe('success')
    expect(statusTone('failed')).toBe('danger')
    expect(statusTone('rejected')).toBe('danger')
    expect(statusTone('excluded')).toBe('neutral')
    expect(statusTone('archive')).toBe('neutral')
  })

  it('splits into batches of at most 20 files', () => {
    const files = Array.from({ length: 45 }, () => ({ size: 1 }))
    expect(splitIntoBatches(files).map((b) => b.length)).toEqual([20, 20, 5])
    expect(splitIntoBatches([])).toEqual([])
  })

  it('splits into batches of at most 200 MB', () => {
    const files = Array.from({ length: 5 }, () => ({ size: 60 * MB }))
    const batches = splitIntoBatches(files)
    expect(batches.map((b) => b.length)).toEqual([3, 2])
    for (const b of batches) expect(b.reduce((s, f) => s + f.size, 0)).toBeLessThanOrEqual(200 * MB)
  })

  it('detects superseded documents', () => {
    const base = { id: 'a', supersedes_id: null, routed_ref: {} } as unknown as TenderDocument
    const newer = { id: 'b', supersedes_id: 'a', routed_ref: {} } as unknown as TenderDocument
    expect(isSuperseded(base, [base, newer])).toBe(true)
    expect(isSuperseded(newer, [base, newer])).toBe(false)
    expect(isSuperseded({ ...newer, routed_ref: { superseded_by: 'c' } }, [newer])).toBe(true)
  })
})
