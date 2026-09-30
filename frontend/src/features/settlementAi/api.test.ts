import { describe, expect, it } from 'vitest'
import { isRunActive, proposalsQuery } from './api'
import { costsRun } from './fixtures'

describe('settlementAi api helpers', () => {
  it('builds the proposals query string', () => {
    expect(proposalsQuery({})).toBe('limit=50&offset=0')
    expect(
      proposalsQuery({ status: 'proposed', flagged: true, noSource: true, minConfidence: 0.6, maxConfidence: 0.85, limit: 10, offset: 20 }),
    ).toBe('status=proposed&flagged=true&no_source=true&min_confidence=0.6&max_confidence=0.85&limit=10&offset=20')
  })

  it('polls only while queued or running', () => {
    expect(isRunActive(costsRun({ status: 'queued' }))).toBe(true)
    expect(isRunActive(costsRun({ status: 'running' }))).toBe(true)
    expect(isRunActive(costsRun({ status: 'ready' }))).toBe(false)
    expect(isRunActive(costsRun({ status: 'failed' }))).toBe(false)
    expect(isRunActive(undefined)).toBe(false)
  })
})
