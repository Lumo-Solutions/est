import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { NextSteps } from './NextSteps'
import { treeSummary } from './testFixtures'
import type { TreeSummary } from './types'

const renderSteps = (summary: TreeSummary) =>
  render(
    <MemoryRouter>
      <NextSteps projectId="p1" summary={summary} />
    </MemoryRouter>,
  )

describe('NextSteps (summary only, no file list)', () => {
  it('links the BOQ and the first drawing from the summary', () => {
    renderSteps(treeSummary({ boq_documents: [{ id: 'b1', name: 'boq.xlsx' }], first_drawing_id: 'dr9', drawings_total: 4, drawings_ready: 1 }))
    expect(screen.getByText('boq.xlsx is ready to import.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('href', '/projects/p1/boq/import?document=b1')
    expect(screen.getByRole('link', { name: 'Open drawings / takeoff' })).toHaveAttribute('href', '/projects/p1/drawings/dr9')
    expect(screen.getByText('1 of 4 drawings ready')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Run verification report' })).toHaveAttribute('href', '/projects/p1/verification')
    expect(screen.getByRole('link', { name: 'Build settlement' })).toHaveAttribute('href', '/projects/p1/settlement')
  })

  it('lets the user pick between several BOQ documents by name', () => {
    renderSteps(treeSummary({ boq_documents: [{ id: 'a', name: 'boq-a.xlsx' }, { id: 'b', name: 'boq-b.xlsx' }] }))
    expect(screen.getByRole('option', { name: 'boq-b.xlsx' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('BOQ document'), { target: { value: 'b' } })
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('href', '/projects/p1/boq/import?document=b')
  })

  it('disables the steps with a reason when there is nothing to open', () => {
    renderSteps(treeSummary({ total: 1 }))
    expect(screen.getByText(/No BOQ has been found yet/)).toBeInTheDocument()
    expect(screen.getByText('No drawings yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('says drawings are still being prepared when there are drawings but no first one yet', () => {
    renderSteps(treeSummary({ drawings_total: 3 }))
    expect(screen.getByText('Drawings are still being prepared.')).toBeInTheDocument()
  })
})
