import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, treeItem } from './testFixtures'

let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const confirmMutate = vi.fn()
const reclassifyMutate = vi.fn()
const bulkMutate = vi.fn()
vi.mock('./api', () => ({
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useConfirmDocument: () => ({ mutate: confirmMutate, isPending: false }),
  useReclassifyDocument: () => ({ mutate: reclassifyMutate, isPending: false }),
  useBulkConfirm: () => ({ mutate: bulkMutate, isPending: false }),
}))

import { NeedsCheckList } from './NeedsCheckList'

const pending = (over = {}) =>
  treeItem({ display_status: 'needs_check', status: 'proposed', doc_class: 'specification', confidence: 0.62, ...over })

describe('NeedsCheckList', () => {
  beforeEach(() => {
    roles = ['lead_estimator']
    confirmMutate.mockReset()
    reclassifyMutate.mockReset()
    bulkMutate.mockReset()
  })

  it('renders nothing when no file needs a check', () => {
    const { container } = render(<NeedsCheckList projectId="p1" items={[treeItem()]} canConfirm />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows name, folder, proposal, confidence, reason and evidence on demand', () => {
    const item = pending({
      name: 'spec-roads.pdf',
      path: 'Tender/Specs/spec-roads.pdf',
      confidence: 0.62,
      decided_by: 'ai',
      status_reason: 'The AI was only 62% sure (threshold 85%).',
      evidence_quote: 'General specification for road works',
      evidence_page: 3,
    })
    render(<NeedsCheckList projectId="p1" items={[item]} canConfirm />)
    expect(screen.getByRole('heading', { name: 'Needs your check (1)' })).toBeInTheDocument()
    expect(screen.getByText('spec-roads.pdf')).toBeInTheDocument()
    expect(screen.getByText('Tender/Specs')).toBeInTheDocument()
    expect(screen.getByText('Specification')).toBeInTheDocument()
    expect(screen.getByText('62% sure')).toBeInTheDocument()
    expect(screen.getByText('AI')).toBeInTheDocument()
    expect(screen.getByText(/only 62% sure/)).toBeInTheDocument()
    expect(screen.queryByText(/General specification/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show evidence/ }))
    expect(screen.getByText(/General specification for road works/)).toBeInTheDocument()
    expect(screen.getByText(/page 3/)).toBeInTheDocument()
  })

  it('Confirm calls confirm for that file', () => {
    const item = pending({ name: 'a.pdf' })
    render(<NeedsCheckList projectId="p1" items={[item]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm a.pdf' }))
    expect(confirmMutate).toHaveBeenCalledTimes(1)
    expect(confirmMutate.mock.calls[0][0]).toBe(item.id)
  })

  it('Change applies a non-drawing class at once with confirm: true', () => {
    const item = pending({ name: 'a.pdf' })
    render(<NeedsCheckList projectId="p1" items={[item]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Change class of a.pdf' }))
    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'boq' } })
    expect(reclassifyMutate).toHaveBeenCalledTimes(1)
    expect(reclassifyMutate.mock.calls[0][0]).toEqual({ id: item.id, doc_class: 'boq', sub_type: null, drawing_type: null, confirm: true })
  })

  it('Change to Drawing asks for discipline and type, then applies', () => {
    const item = pending({ name: 'a.pdf' })
    render(<NeedsCheckList projectId="p1" items={[item]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Change class of a.pdf' }))
    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'drawing' } })
    expect(reclassifyMutate).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Discipline'), { target: { value: 'stormwater' } })
    fireEvent.change(screen.getByLabelText('Drawing type'), { target: { value: 'plan_profile' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply as drawing' }))
    expect(reclassifyMutate.mock.calls[0][0]).toEqual({
      id: item.id,
      doc_class: 'drawing',
      sub_type: 'stormwater',
      drawing_type: 'plan_profile',
      confirm: true,
    })
  })

  it('Confirm all shown sends explicit ids and leaves conflict and injection files out', () => {
    const ok1 = pending({ name: 'ok1.pdf' })
    const ok2 = pending({ name: 'ok2.pdf', flags: ['low_confidence'] })
    const conflict = pending({ name: 'conflict.pdf', flags: ['conflict'] })
    const inj = pending({ name: 'inj.pdf', flags: ['injection_suspected'] })
    render(<NeedsCheckList projectId="p1" items={[ok1, ok2, conflict, inj]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all shown (2)' }))
    // Nothing is sent before the confirmation step.
    expect(bulkMutate).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: 'Confirm all shown?' })
    expect(dialog).toHaveTextContent('2 with a conflict or suspicious text stay here')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm all' }))
    expect(bulkMutate.mock.calls[0][0]).toEqual({ document_ids: [ok1.id, ok2.id] })
  })

  it('is read-only below lead estimator', () => {
    roles = ['estimator']
    render(<NeedsCheckList projectId="p1" items={[pending({ name: 'a.pdf' })]} canConfirm={false} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change class/ })).not.toBeInTheDocument()
    expect(screen.getByText(/need a lead estimator or above/)).toBeInTheDocument()
  })

  it('shows a failed confirm next to its row', () => {
    const item = pending({ name: 'a.pdf' })
    confirmMutate.mockImplementation((_id, opts) => opts.onError(new Error('Nope')))
    render(<NeedsCheckList projectId="p1" items={[item]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm a.pdf' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Could not confirm a.pdf: Nope')
  })
})
