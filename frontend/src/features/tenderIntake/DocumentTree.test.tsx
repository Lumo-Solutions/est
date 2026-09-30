import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, treeItem } from './testFixtures'
import type { TreeItem } from './types'

const reclassifyMutate = vi.fn()
const bulkAsync = vi.fn()
const excludeMutate = vi.fn()
const rerunMutate = vi.fn()
vi.mock('./api', () => ({
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useReclassifyDocument: () => ({ mutate: reclassifyMutate, isPending: false }),
  useBulkReclassify: () => ({ mutateAsync: bulkAsync, isPending: false }),
  useExclude: () => ({ mutate: excludeMutate, isPending: false }),
  useRerun: () => ({ mutate: rerunMutate, isPending: false }),
  useTenderDocument: () => ({ data: undefined, isLoading: false, isError: false }),
}))

import { DocumentTree } from './DocumentTree'

function sample(): TreeItem[] {
  return [
    treeItem({
      id: 'd1', name: 'C-101.pdf', path: 'Tender/Drawings/C-101.pdf', doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'plan_profile',
      document_number: 'RD-101', title: 'Main road plan', revision: 'B', sheet_number: '1', scale: '1:500', unit_type: 'type_2',
      confidence: 0.93, decided_by: 'ai', auto_accepted: true, routed_kind: 'drawing', drawing_id: 'dr1',
    }),
    treeItem({ id: 'd2', name: 'C-102.pdf', path: 'Tender/Drawings/C-102.pdf', doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'cross_sections', confidence: 0.9, decided_by: 'ai', auto_accepted: true }),
    treeItem({ id: 'd3', name: 'S-201.pdf', path: 'Tender/Drawings/S-201.pdf', doc_class: 'drawing', discipline: 'stormwater', drawing_type: 'plan_profile' }),
    treeItem({ id: 'b1', name: 'boq.xlsx', path: 'Tender/boq.xlsx', doc_class: 'boq', confidence: 0.97, decided_by: 'user', flags: ['duplicate'] }),
    treeItem({ id: 's1', name: 'spec.pdf', path: 'Tender/Docs/spec.pdf', doc_class: 'specification', decided_by: 'rules', flags: ['rules_fallback'] }),
    treeItem({ id: 'a1', name: 'addendum1.pdf', doc_class: 'addendum', supersedes: ['C-101 Rev A'] }),
    treeItem({ id: 'f1', name: 'broken.pdf', doc_class: 'other', display_status: 'failed', status: 'failed', status_reason: 'Could not read the file' }),
    treeItem({ id: 'n1', name: 'unknown.pdf', path: 'loose/unknown.pdf', doc_class: null, display_status: 'reading' }),
  ]
}

const renderTree = (items = sample(), canConfirm = true) => render(<DocumentTree projectId="p1" items={items} canConfirm={canConfirm} />)
const groupNames = () => screen.getAllByRole('group').map((g) => g.getAttribute('aria-label') ?? '')
const rowOf = (name: string) => within(screen.getByText(name).closest('li') as HTMLElement)

describe('DocumentTree', () => {
  beforeEach(() => {
    reclassifyMutate.mockReset()
    bulkAsync.mockReset()
    excludeMutate.mockReset()
    rerunMutate.mockReset()
  })

  it('groups by class, then discipline, then drawing type, with counts', () => {
    renderTree()
    const names = groupNames()
    expect(names).toEqual(
      expect.arrayContaining([
        'Drawing, 3 files',
        'Roads / civil, 2 files',
        'Plan & profile / longitudinal section, 1 file',
        'Cross sections, 1 file',
        'Stormwater drainage, 1 file',
        'Bill of quantities, 1 file',
        'Addendum, 1 file',
        'Specification, 1 file',
        'Not classified yet, 1 file',
      ]),
    )
    // Drawing comes before BOQ, and Not classified yet is last.
    expect(names.indexOf('Drawing, 3 files')).toBeLessThan(names.indexOf('Bill of quantities, 1 file'))
    expect(names.at(-1)).toBe('Not classified yet, 1 file')
    expect(screen.getByText('8 files')).toBeInTheDocument()
  })

  it('shows drawing chips, status, decided-by and flag badges on a row', () => {
    renderTree()
    const r = rowOf('C-101.pdf')
    expect(r.getByText('RD-101')).toBeInTheDocument()
    expect(r.getByText('Main road plan')).toBeInTheDocument()
    expect(r.getByText('Rev B')).toBeInTheDocument()
    expect(r.getByText('Sheet 1')).toBeInTheDocument()
    expect(r.getByText('1:500')).toBeInTheDocument()
    expect(r.getByText('Type 2')).toBeInTheDocument()
    expect(r.getByText('93%')).toBeInTheDocument()
    expect(r.getByText('Ready')).toBeInTheDocument()
    expect(r.getByText('AI (auto-accepted)')).toBeInTheDocument()
    expect(r.queryByRole('button', { name: /Re-run/ })).not.toBeInTheDocument()

    expect(rowOf('boq.xlsx').getByText('Duplicate')).toBeInTheDocument()
    expect(rowOf('boq.xlsx').getByText('You')).toBeInTheDocument()
    expect(rowOf('spec.pdf').getAllByText('Classified by rules')).toHaveLength(1)
    expect(screen.getByText('Supersedes: C-101 Rev A')).toBeInTheDocument()
    const broken = rowOf('broken.pdf')
    expect(broken.getByText('Failed')).toBeInTheDocument()
    expect(broken.getByText('Could not read the file')).toBeInTheDocument()
    expect(broken.getByRole('button', { name: 'Re-run broken.pdf' })).toBeInTheDocument()
  })

  it('collapses and expands a group', () => {
    renderTree()
    const group = screen.getByRole('group', { name: 'Bill of quantities, 1 file' })
    const toggle = within(group).getAllByRole('button')[0]
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('boq.xlsx')).not.toBeInTheDocument()
  })

  it('switches to the original folders', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Original folders' }))
    expect(screen.getByRole('button', { name: 'Original folders' })).toHaveAttribute('aria-pressed', 'true')
    expect(groupNames()).toEqual(
      expect.arrayContaining(['Tender, 5 files', 'Drawings, 3 files', 'Docs, 1 file', 'loose, 1 file', 'Top level (no folder), 2 files']),
    )
    expect(screen.queryByRole('group', { name: /^Drawing,/ })).not.toBeInTheDocument()
  })

  it('searches and filters with a live result count', () => {
    renderTree()
    fireEvent.change(screen.getByLabelText('Search documents'), { target: { value: 'rd-101' } })
    expect(screen.getByText('1 of 8 files match')).toBeInTheDocument()
    expect(screen.getByText('C-101.pdf')).toBeInTheDocument()
    expect(screen.queryByText('C-102.pdf')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'failed' } })
    expect(screen.getByText('1 of 8 files match')).toBeInTheDocument()
    expect(screen.getByText('broken.pdf')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Decided by'), { target: { value: 'user' } })
    expect(screen.getByText('boq.xlsx')).toBeInTheDocument()
    expect(screen.getByText('1 of 8 files match')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search documents'), { target: { value: 'zzz' } })
    expect(screen.getByText('No files match your search or filters.')).toBeInTheDocument()
  })

  it('changes the class of one file with confirm: true', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Change class of spec.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class of spec.pdf' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'boq' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(reclassifyMutate.mock.calls[0][0]).toEqual({ id: 's1', doc_class: 'boq', sub_type: null, drawing_type: null, confirm: true })
  })

  it('warns before a routed drawing leaves the takeoff', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Change class of C-101.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class of C-101.pdf' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'specification' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(reclassifyMutate).not.toHaveBeenCalled()
    const warn = screen.getByRole('dialog', { name: 'Take this out of the takeoff?' })
    expect(warn).toHaveTextContent('measurements are archived, not deleted')
    fireEvent.click(within(warn).getByRole('button', { name: 'Change class' }))
    expect(reclassifyMutate.mock.calls[0][0]).toMatchObject({ id: 'd1', doc_class: 'specification', confirm: true })
  })

  it('does not warn when a drawing stays a drawing (discipline change)', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Change class of C-101.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class of C-101.pdf' })
    fireEvent.change(within(dialog).getByLabelText('Discipline'), { target: { value: 'sewer' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(reclassifyMutate.mock.calls[0][0]).toEqual({ id: 'd1', doc_class: 'drawing', sub_type: 'sewer', drawing_type: 'plan_profile', confirm: true })
  })

  it('bulk changes the class of the selected files and lists per-file failures', async () => {
    bulkAsync.mockResolvedValue({
      confirmed: 1,
      failed: 1,
      skipped: 0,
      results: [
        { id: 's1', ok: true, status: 'routed', routed_kind: 'register', error: null },
        { id: 'a1', ok: false, status: null, routed_kind: null, error: 'Cannot route' },
      ],
    })
    renderTree()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select spec.pdf' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select addendum1.pdf' }))
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 2 files' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    await waitFor(() => expect(bulkAsync).toHaveBeenCalled())
    const body = bulkAsync.mock.calls[0][0]
    expect([...body.document_ids].sort()).toEqual(['a1', 's1'])
    expect(body).toMatchObject({ doc_class: 'other', sub_type: null, drawing_type: null, confirm: true })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('addendum1.pdf: Cannot route')
    expect(screen.getByRole('status')).toHaveTextContent('Changed 1, failed 1')
  })

  it('the group checkbox selects every file below it', () => {
    renderTree()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all 3 in Drawing' }))
    expect(screen.getByRole('button', { name: 'Change class for 3 files' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Select C-102.pdf' })).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(screen.queryByRole('button', { name: /Change class for/ })).not.toBeInTheDocument()
  })

  it('asks for a reason before excluding', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Exclude spec.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Exclude spec.pdf?' })
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Superseded by addendum' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Exclude' }))
    expect(excludeMutate.mock.calls[0][0]).toEqual({ id: 's1', reason: 'Superseded by addendum' })
  })

  it('opens the evidence modal', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'View evidence for spec.pdf' }))
    expect(screen.getByRole('dialog', { name: 'Evidence for spec.pdf' })).toBeInTheDocument()
  })

  it('is read-only without the confirm role but still offers evidence and download', () => {
    renderTree(sample(), false)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change class/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Exclude/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View evidence for spec.pdf' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download spec.pdf' })).toHaveAttribute('href', '/api/v1/tender-documents/s1/download')
  })

  it('stays responsive with 300+ files: collapsed groups render nothing, long groups page by 100', () => {
    const many = Array.from({ length: 320 }, (_, i) => treeItem({ name: `spec-${i}.pdf`, doc_class: 'specification' }))
    const { container } = renderTree(many)
    // Text and <li> queries: role queries over hundreds of rows are needlessly slow in jsdom.
    const rows = () => container.querySelectorAll('li').length
    const toggle = within(screen.getByRole('group', { name: 'Specification, 320 files' })).getAllByRole('button')[0]
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(rows()).toBe(0)
    fireEvent.click(toggle)
    expect(rows()).toBe(100)
    fireEvent.click(screen.getByText('Show 100 more (220 not shown)'))
    expect(rows()).toBe(200)
    fireEvent.click(screen.getByText('Show 100 more (120 not shown)'))
    fireEvent.click(screen.getByText('Show 20 more (20 not shown)'))
    expect(rows()).toBe(320)
    expect(screen.queryByText(/Show .* more/)).not.toBeInTheDocument()
  })
})
