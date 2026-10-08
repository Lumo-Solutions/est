import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, treeItem, treeSummary } from './testFixtures'
import type { DocFilter, TreeItem } from './types'

const m = vi.hoisted(() => ({
  confirmMutate: vi.fn(),
  reclassifyMutate: vi.fn(),
  bulkAsync: vi.fn(),
  invalidate: vi.fn(),
  fetchNextPage: vi.fn(),
  rows: [] as unknown[],
  listTotal: 0,
  hasNextPage: false,
  confirmable: 0,
  calls: [] as { filter: DocFilter | null; options: { enabled?: boolean; limit?: number } | undefined }[],
}))
vi.mock('./api', () => ({
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useConfirmDocument: () => ({ mutate: m.confirmMutate, isPending: false }),
  useReclassifyDocument: () => ({ mutate: m.reclassifyMutate, isPending: false }),
  useBulkConfirm: () => ({ mutateAsync: m.bulkAsync, isPending: false }),
  useInvalidateIntake: () => m.invalidate,
  useTenderItems: (_p: string, filter: DocFilter | null, options?: { enabled?: boolean; limit?: number }) => {
    m.calls.push({ filter, options })
    const base = { isLoading: false, isError: false, isFetchingNextPage: false, fetchNextPage: m.fetchNextPage }
    // The "Confirm all" count query asks for has_class files with limit 1; everything else is the paged list.
    if (filter?.has_class) return { ...base, data: { pages: [{ items: [], total: m.confirmable, limit: 1, offset: 0 }] }, hasNextPage: false }
    return { ...base, data: { pages: [{ items: m.rows as TreeItem[], total: m.listTotal, limit: 25, offset: 0 }] }, hasNextPage: m.hasNextPage }
  },
}))

import { NeedsCheckList } from './NeedsCheckList'

const pending = (over = {}) => treeItem({ display_status: 'needs_check', status: 'proposed', doc_class: 'specification', confidence: 0.62, ...over })

function setup(rows: TreeItem[], opts: { needsCheck?: number; confirmable?: number; canConfirm?: boolean } = {}) {
  m.rows = rows
  m.listTotal = opts.needsCheck ?? rows.length
  m.confirmable = opts.confirmable ?? rows.length
  return render(<NeedsCheckList projectId="p1" summary={treeSummary({ needs_check: opts.needsCheck ?? rows.length })} canConfirm={opts.canConfirm ?? true} />)
}

describe('NeedsCheckList', () => {
  beforeEach(() => {
    for (const f of [m.confirmMutate, m.reclassifyMutate, m.bulkAsync, m.invalidate, m.fetchNextPage]) f.mockReset()
    m.calls = []
    m.hasNextPage = false
  })

  it('renders nothing when no file needs a check', () => {
    const { container } = setup([], { needsCheck: 0 })
    expect(container).toBeEmptyDOMElement()
  })

  it('pages the list from the server (25 a time) and takes the header count from the summary', () => {
    m.hasNextPage = true
    setup([pending({ name: 'a.pdf' })], { needsCheck: 1200 })
    expect(screen.getByRole('heading', { name: 'Needs your check (1200)' })).toBeInTheDocument()
    expect(m.calls.some((c) => c.filter?.display_status === 'needs_check' && !c.filter.has_class && c.options?.limit === 25)).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: /Show 25 more/ }))
    expect(m.fetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('shows name, folder, proposal, confidence, reason and evidence on demand', () => {
    setup([
      pending({
        name: 'spec-roads.pdf',
        path: 'Tender/Specs/spec-roads.pdf',
        decided_by: 'ai',
        status_reason: 'The AI was only 62% sure (threshold 85%).',
        evidence_quote: 'General specification for road works',
        evidence_page: 3,
      }),
    ])
    expect(screen.getByText('Tender/Specs')).toBeInTheDocument()
    expect(screen.getByText('Specification')).toBeInTheDocument()
    expect(screen.getByText('62% sure')).toBeInTheDocument()
    expect(screen.getByText(/only 62% sure/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show evidence/ }))
    expect(screen.getByText(/General specification for road works/)).toBeInTheDocument()
  })

  it('Confirm calls confirm for that file', () => {
    const item = pending({ name: 'a.pdf' })
    setup([item])
    fireEvent.click(screen.getByRole('button', { name: 'Confirm a.pdf' }))
    expect(m.confirmMutate.mock.calls[0][0]).toBe(item.id)
  })

  it('a file with no proposed class (too large) has no Confirm button, only Change, its reason and a Too large badge', () => {
    const item = pending({
      name: 'huge.pdf',
      doc_class: null,
      confidence: null,
      flags: ['too_large'],
      status_reason: 'Too large to read automatically: 900 pages. Choose its class yourself.',
    })
    setup([item])
    expect(screen.queryByRole('button', { name: 'Confirm huge.pdf' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change class of huge.pdf' })).toBeInTheDocument()
    expect(screen.getByText('Too large')).toBeInTheDocument()
    expect(screen.getByText(/Too large to read automatically/)).toBeInTheDocument()
    expect(screen.getByText('No class proposed')).toBeInTheDocument()
  })

  it('Change applies a non-drawing class at once with confirm: true', () => {
    const item = pending({ name: 'a.pdf' })
    setup([item])
    fireEvent.click(screen.getByRole('button', { name: 'Change class of a.pdf' }))
    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'boq' } })
    expect(m.reclassifyMutate.mock.calls[0][0]).toEqual({ id: item.id, doc_class: 'boq', sub_type: null, drawing_type: null, confirm: true })
  })

  it('Change to Drawing asks for discipline and type, then applies', () => {
    const item = pending({ name: 'a.pdf' })
    setup([item])
    fireEvent.click(screen.getByRole('button', { name: 'Change class of a.pdf' }))
    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'drawing' } })
    expect(m.reclassifyMutate).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Discipline'), { target: { value: 'stormwater' } })
    fireEvent.change(screen.getByLabelText('Drawing type'), { target: { value: 'plan_profile' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply as drawing' }))
    expect(m.reclassifyMutate.mock.calls[0][0]).toEqual({ id: item.id, doc_class: 'drawing', sub_type: 'stormwater', drawing_type: 'plan_profile', confirm: true })
  })

  it('counts Confirm all from a server query with the has_class and exclude_flags filter', () => {
    setup([pending({ name: 'a.pdf' })], { needsCheck: 2500, confirmable: 2400 })
    expect(screen.getByRole('button', { name: 'Confirm all (2400)' })).toBeInTheDocument()
    const countCall = m.calls.find((c) => c.filter?.has_class)
    expect(countCall?.filter).toEqual({ display_status: 'needs_check', has_class: true, exclude_flags: ['conflict', 'injection_suspected'] })
    expect(countCall?.options?.limit).toBe(1)
  })

  it('Confirm all confirms every matching file server-side, looping the cursor with live progress', async () => {
    const filter = { display_status: 'needs_check', has_class: true, exclude_flags: ['conflict', 'injection_suspected'] }
    m.bulkAsync
      .mockResolvedValueOnce({ confirmed: 100, failed: 0, skipped: 0, results: [], matched: 250, next_cursor: 'c1' })
      .mockResolvedValueOnce({ confirmed: 99, failed: 1, skipped: 0, results: [{ id: 'bad1', ok: false, status: null, routed_kind: null, error: 'Cannot route' }], matched: 250, next_cursor: 'c2' })
      .mockResolvedValueOnce({ confirmed: 50, failed: 0, skipped: 0, results: [], matched: 250, next_cursor: null })
    setup([pending({ name: 'a.pdf' })], { needsCheck: 260, confirmable: 250 })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all (250)' }))
    // Nothing is sent before the confirmation step, which says how many go and how many are held back.
    expect(m.bulkAsync).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: 'Confirm all?' })
    expect(dialog).toHaveTextContent('Route 250 files as proposed.')
    expect(dialog).toHaveTextContent('10 stay here for a one-by-one check')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm all' }))
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalledTimes(3))
    expect(m.bulkAsync.mock.calls.map((c) => c[0])).toEqual([
      { filter, cursor: null },
      { filter, cursor: 'c1' },
      { filter, cursor: 'c2' },
    ])
    expect(await screen.findByText('Confirmed 249 of 250, failed 1')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('bad1: Cannot route')
    expect(m.invalidate).toHaveBeenCalledTimes(1)
  })

  it('shows Confirmed X of N while running and Cancel stops after the current chunk', async () => {
    let release: (v: unknown) => void = () => {}
    m.bulkAsync.mockImplementationOnce(() => new Promise((res) => (release = res)))
    setup([pending({ name: 'a.pdf' })], { needsCheck: 300, confirmable: 300 })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all (300)' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Confirm all?' })).getByRole('button', { name: 'Confirm all' }))
    expect(await screen.findByText('Confirmed 0 of 300')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    release({ confirmed: 100, failed: 0, skipped: 0, results: [], matched: 300, next_cursor: 'c1' })
    expect(await screen.findByText('Stopped. Confirmed 100 of 300')).toBeInTheDocument()
    expect(m.bulkAsync).toHaveBeenCalledTimes(1)
  })

  it('caps the failure list at 20 and says how many more', async () => {
    const results = Array.from({ length: 25 }, (_, i) => ({ id: `f${i}`, ok: false, status: null, routed_kind: null, error: 'No' }))
    m.bulkAsync.mockResolvedValueOnce({ confirmed: 0, failed: 25, skipped: 0, results, matched: 25, next_cursor: null })
    setup([pending({ name: 'a.pdf' })], { needsCheck: 25, confirmable: 25 })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all (25)' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Confirm all?' })).getByRole('button', { name: 'Confirm all' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getAllByRole('listitem')).toHaveLength(21)
    expect(alert).toHaveTextContent('and 5 more')
  })

  it('is read-only below lead estimator', () => {
    setup([pending({ name: 'a.pdf' })], { canConfirm: false })
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change class/ })).not.toBeInTheDocument()
    expect(screen.getByText(/need a lead estimator or above/)).toBeInTheDocument()
  })

  it('shows a failed confirm next to its row', () => {
    m.confirmMutate.mockImplementation((_id, opts) => opts.onError(new Error('Nope')))
    setup([pending({ name: 'a.pdf' })])
    fireEvent.click(screen.getByRole('button', { name: 'Confirm a.pdf' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Could not confirm a.pdf: Nope')
  })
})
