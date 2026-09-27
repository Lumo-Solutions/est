import { describe, expect, it } from 'vitest'
import { formatMarginPct } from './format'

describe('formatMarginPct', () => {
  it('keeps 3 decimal places, the precision app/services/approvals.py actually routes on', () => {
    expect(formatMarginPct(7.995)).toBe('7.995')
  })

  it('does not round a below-floor margin up to the routing floor', () => {
    // 7.995 rounds to "8.00" at 2dp, which would look like it stayed at
    // bd_director even though the real Decimal routing (margin_pct <
    // max_margin_pct) escalates it to managing_director.
    expect(formatMarginPct(7.995)).not.toBe('8.00')
  })

  it('still reads as a plain 2dp value when the margin has no third-decimal component', () => {
    expect(formatMarginPct(8)).toBe('8.000')
  })
})
