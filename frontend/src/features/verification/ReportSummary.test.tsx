import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { VerificationRunOut } from '../../types/api'
import { TopRisks } from './ReportSummary'

function runWith(top_risks: VerificationRunOut['summary']['top_risks']) {
  return { summary: { verifiable: 1, by_trade: [], top_risks } } as unknown as VerificationRunOut
}

describe('TopRisks', () => {
  it('renders a risk that has no BOQ line (missing in BOQ) without crashing, and is not clickable', () => {
    const describeLine = vi.fn((id: string) => `line ${id}`)
    render(
      <TopRisks
        run={runWith([
          { line_id: null, class: 'missing_in_boq', delta_pct: null, note: '80 m of 450mm storm pipe is drawn but not in the BOQ' },
          { line_id: 'abc', class: 'variance', delta_pct: 50, note: '' },
        ])}
        describe={describeLine}
        onOpen={vi.fn()}
      />,
    )
    expect(screen.getByText('Drawing item with no BOQ line')).toBeInTheDocument()
    expect(screen.getByText(/80 m of 450mm storm pipe/)).toBeInTheDocument()
    expect(describeLine).toHaveBeenCalledTimes(1)
    expect(describeLine).toHaveBeenCalledWith('abc')
  })

  it('opens a line risk', () => {
    const onOpen = vi.fn()
    render(<TopRisks run={runWith([{ line_id: 'abc', class: 'variance', delta_pct: 50, note: '' }])} describe={(id) => `line ${id}`} onOpen={onOpen} />)
    fireEvent.click(screen.getByRole('button', { name: 'line abc' }))
    expect(onOpen).toHaveBeenCalledWith('abc')
  })
})
