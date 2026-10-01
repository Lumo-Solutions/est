import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MeasurementState } from '../../types/api'
import { MeasurementBadge } from './MeasurementBadge'

describe('MeasurementBadge', () => {
  it.each<[MeasurementState, string]>([
    ['indexed', 'Not measured yet'],
    ['queued', 'Queued to measure'],
    ['measuring', 'Measuring'],
    ['measured', 'Measured'],
    ['failed', 'Measuring failed'],
  ])('shows a text label for %s', (state, label) => {
    render(<MeasurementBadge state={state} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('shows the failure reason as visible text', () => {
    render(<MeasurementBadge state="failed" errorMessage="PDF is encrypted" />)
    expect(screen.getByText('PDF is encrypted')).toBeInTheDocument()
  })

  it('does not show an error message for other states', () => {
    render(<MeasurementBadge state="measured" errorMessage="old error" />)
    expect(screen.queryByText('old error')).toBeNull()
  })
})
