import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, groupCount, treeItem, treeSummary } from './testFixtures'
import type { DocFilter, FolderCount, GroupCount, TreeItem } from './types'
import { mockElementSizes } from './virtualTestUtils'

mockElementSizes({ viewport: 448, row: 64 })

const m = vi.hoisted(() => ({
  reclassifyMutate: vi.fn(),
  bulkAsync: vi.fn(),
  excludeMutate: vi.fn(),
  rerunMutate: vi.fn(),
  invalidate: vi.fn(),
  itemsCalls: [] as { filter: DocFilter | null; options: { enabled?: boolean; limit?: number } | undefined }[],
  db: [] as unknown[],
  forcedTotal: null as number | null,
  fetchNextPage: vi.fn(),
  hasNextPage: false,
  readFiles: new Set<string>(),
}))

// A tiny in-memory version of the server's /items filter, so the tests see what the real list would return.
function matches(i: TreeItem, f: DocFilter): boolean {
  const eq = (v: string | null, want?: string) => want === undefined || (want === 'none' ? !v : v === want)
  if (!eq(i.doc_class, f.doc_class) || !eq(i.discipline, f.discipline) || !eq(i.drawing_type, f.drawing_type)) return false
  if (f.display_status && i.display_status !== f.display_status) return false
  if (f.decided_by && i.decided_by !== f.decided_by) return false
  if (f.q && ![i.name, i.path, i.document_number, i.title].some((v) => v?.toLowerCase().includes(f.q!.toLowerCase()))) return false
  if (f.folder !== undefined) {
    const folder = (i.path ?? '').split('/').slice(0, -1).join('/')
    if (f.include_subfolders ? !(folder === f.folder || folder.startsWith(`${f.folder}/`)) : folder !== f.folder) return false
  }
  return true
}

vi.mock('../agentLines/useAgentReadFiles', () => ({ useAgentReadFiles: () => m.readFiles }))

vi.mock('./api', () => ({
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useReclassifyDocument: () => ({ mutate: m.reclassifyMutate, isPending: false }),
  useBulkReclassify: () => ({ mutateAsync: m.bulkAsync, isPending: false }),
  useExclude: () => ({ mutate: m.excludeMutate, isPending: false }),
  useRerun: () => ({ mutate: m.rerunMutate, isPending: false }),
  useInvalidateIntake: () => m.invalidate,
  useTenderDocument: () => ({ data: undefined, isLoading: false, isError: false }),
  useTenderItems: (_p: string, filter: DocFilter | null, options?: { enabled?: boolean; limit?: number }) => {
    m.itemsCalls.push({ filter, options })
    const idle = { data: undefined, isLoading: false, isError: false, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: m.fetchNextPage }
    if (filter === null || options?.enabled === false) return idle
    const items = (m.db as TreeItem[]).filter((i) => matches(i, filter))
    return {
      ...idle,
      data: { pages: [{ items, total: m.forcedTotal ?? items.length, limit: 100, offset: 0 }] },
      hasNextPage: m.hasNextPage,
    }
  },
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
    treeItem({ id: 'a1', name: 'addendum1.pdf', path: 'loose/addendum1.pdf', doc_class: 'addendum' }),
    treeItem({ id: 'x1', name: 'mystery.pdf', doc_class: null, display_status: 'needs_check', status_reason: 'No class' }),
    treeItem({ id: 'f1', name: 'broken.pdf', doc_class: null, display_status: 'failed', status_reason: 'Could not read the file' }),
  ]
}

const GROUPS: GroupCount[] = [
  groupCount('drawing', 1, 'roads_civil', 'plan_profile'),
  groupCount('drawing', 1, 'roads_civil', 'cross_sections'),
  groupCount('drawing', 1, 'stormwater', 'plan_profile'),
  groupCount('boq', 1),
  groupCount('specification', 1),
  groupCount('addendum', 1),
  groupCount(null, 2),
]
const FOLDERS: FolderCount[] = [
  { folder: 'Tender/Drawings', count: 3 },
  { folder: 'Tender', count: 1 },
  { folder: 'Tender/Docs', count: 1 },
  { folder: 'loose', count: 1 },
  { folder: '', count: 2 },
]

function renderTree(opts: { groups?: GroupCount[]; folders?: FolderCount[]; total?: number; canConfirm?: boolean } = {}) {
  const groups = opts.groups ?? GROUPS
  const total = opts.total ?? groups.reduce((n, g) => n + g.count, 0)
  return render(
    <DocumentTree projectId="p1" summary={treeSummary({ total })} groups={groups} folders={opts.folders ?? FOLDERS} canConfirm={opts.canConfirm ?? true} />,
  )
}

const rowOf = (name: string) => within(screen.getByText(name).closest('[role="listitem"]') as HTMLElement)
const groupNames = () => screen.getAllByRole('group').map((g) => g.getAttribute('aria-label'))
const lastFilters = () => m.itemsCalls.map((c) => c.filter).filter((f): f is DocFilter => f !== null)
const toggleOf = (name: string) => within(screen.getByRole('group', { name })).getAllByRole('button')[0]

describe('DocumentTree', () => {
  beforeEach(() => {
    m.db = sample()
    m.forcedTotal = null
    m.hasNextPage = false
    m.readFiles = new Set()
    m.itemsCalls = []
    for (const f of [m.reclassifyMutate, m.bulkAsync, m.excludeMutate, m.rerunMutate, m.invalidate, m.fetchNextPage]) f.mockReset()
  })

  it('builds the type groups from the counts alone and rolls them up', () => {
    // 8 files is a small tree, so everything is open and each group fetches its own files.
    renderTree()
    const names = groupNames()
    expect(names).toEqual(
      expect.arrayContaining([
        'Drawing, 3 files',
        'Bill of quantities, 1 file',
        'Addendum, 1 file',
        'Specification, 1 file',
        'Not classified yet, 2 files',
      ]),
    )
    expect(names.indexOf('Drawing, 3 files')).toBeLessThan(names.indexOf('Bill of quantities, 1 file'))
    expect(names.at(-1)).toBe('Not classified yet, 2 files')
    expect(screen.getByText('8 files')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Roads / civil, 2 files' })).toBeInTheDocument()
  })

  it('collapses groups on a big tree and fetches a group only when it is opened, with that group filter', () => {
    renderTree({ total: 5000 })
    // Drawings and BOQ start open; the drawing groups hold sub-groups, only the BOQ lists files.
    expect(toggleOf('Drawing, 3 files')).toHaveAttribute('aria-expanded', 'true')
    expect(toggleOf('Specification, 1 file')).toHaveAttribute('aria-expanded', 'false')
    expect(lastFilters()).toContainEqual({ doc_class: 'boq' })
    expect(lastFilters()).not.toContainEqual({ doc_class: 'specification' })
    expect(screen.queryByText('spec.pdf')).not.toBeInTheDocument()

    fireEvent.click(toggleOf('Specification, 1 file'))
    expect(lastFilters()).toContainEqual({ doc_class: 'specification' })
    expect(screen.getByText('spec.pdf')).toBeInTheDocument()

    fireEvent.click(toggleOf('Not classified yet, 2 files'))
    expect(lastFilters()).toContainEqual({ doc_class: 'none' })

    const roads = screen.getByRole('group', { name: 'Roads / civil, 2 files' })
    fireEvent.click(within(roads).getAllByRole('button')[1])
    expect(lastFilters()).toContainEqual({ doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'plan_profile' })
  })

  it('shows the Original folders tree from the folder counts: exact folder for a node own files', () => {
    renderTree({ total: 5000 })
    fireEvent.click(screen.getByRole('button', { name: 'Original folders' }))
    const names = groupNames()
    expect(names).toEqual(expect.arrayContaining(['Tender, 5 files', 'loose, 1 file', 'Top level (no folder), 2 files']))
    // Top-level folders start open, their sub-folders closed.
    fireEvent.click(toggleOf('Drawings, 3 files'))
    expect(lastFilters()).toContainEqual({ folder: 'Tender/Drawings' })
    expect(lastFilters()).toContainEqual({ folder: 'Tender' })
    fireEvent.click(toggleOf('Top level (no folder), 2 files'))
    expect(lastFilters()).toContainEqual({ folder: '' })
    expect(screen.queryByRole('group', { name: /^Drawing,/ })).not.toBeInTheDocument()
  })

  it('shows drawing chips, status, decided-by and flag badges on a row', () => {
    renderTree()
    const r = rowOf('C-101.pdf')
    expect(r.getByText('RD-101')).toBeInTheDocument()
    expect(r.getByText('Rev B')).toBeInTheDocument()
    expect(r.getByText('Type 2')).toBeInTheDocument()
    expect(r.getByText('93%')).toBeInTheDocument()
    expect(r.getByText('AI (auto-accepted)')).toBeInTheDocument()
    expect(rowOf('boq.xlsx').getByText('Duplicate')).toBeInTheDocument()
    const broken = rowOf('broken.pdf')
    expect(broken.getByText('Could not read the file')).toBeInTheDocument()
    expect(broken.getByRole('button', { name: 'Re-run broken.pdf' })).toBeInTheDocument()
  })

  it('renders a bounded number of DOM rows for a group of 2,000 files and offers Load more', () => {
    const many = Array.from({ length: 100 }, (_, i) => treeItem({ name: `spec-${i}.pdf`, doc_class: 'specification' }))
    m.db = many
    m.forcedTotal = 2000
    m.hasNextPage = true
    const { container } = renderTree({ groups: [groupCount('specification', 2000)], total: 2000 })
    fireEvent.click(toggleOf('Specification, 2000 files'))
    const rendered = container.querySelectorAll('[role="listitem"]').length
    expect(rendered).toBeGreaterThan(0)
    expect(rendered).toBeLessThan(40)
    expect(screen.getByText('100 of 2000 shown')).toBeInTheDocument()
    m.fetchNextPage.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(m.fetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('switches to one flat server-side list when a filter is active', async () => {
    renderTree()
    fireEvent.change(screen.getByLabelText('Search documents'), { target: { value: 'rd-101' } })
    expect(await screen.findByText('1 file matches')).toBeInTheDocument()
    expect(lastFilters().at(-1)).toEqual({ q: 'rd-101' })
    expect(screen.getByText('C-101.pdf')).toBeInTheDocument()
    expect(screen.queryByText('C-102.pdf')).not.toBeInTheDocument()
    expect(screen.queryAllByRole('group').filter((g) => /files?$/.test(g.getAttribute('aria-label') ?? '') && !/Group/.test(g.getAttribute('aria-label') ?? ''))).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'failed' } })
    expect(lastFilters().at(-1)).toEqual({ display_status: 'failed' })
    expect(await screen.findByText('1 file matches')).toBeInTheDocument()
    expect(screen.getByText('broken.pdf')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Decided by'), { target: { value: 'user' } })
    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'boq' } })
    expect(lastFilters().at(-1)).toEqual({ doc_class: 'boq', decided_by: 'user' })
    expect(screen.getByText('boq.xlsx')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Class'), { target: { value: 'none' } })
    fireEvent.change(screen.getByLabelText('Decided by'), { target: { value: '' } })
    expect(lastFilters().at(-1)).toEqual({ doc_class: 'none' })

    fireEvent.change(screen.getByLabelText('Class'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Search documents'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No files match your search or filters.')).toBeInTheDocument()
  })

  it('changes the class of one file with confirm: true', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Change class of spec.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class of spec.pdf' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'boq' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(m.reclassifyMutate.mock.calls[0][0]).toEqual({ id: 's1', doc_class: 'boq', sub_type: null, drawing_type: null, confirm: true })
  })

  it('warns before a routed drawing leaves the takeoff', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Change class of C-101.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class of C-101.pdf' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'specification' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(m.reclassifyMutate).not.toHaveBeenCalled()
    const warn = screen.getByRole('dialog', { name: 'Take this out of the takeoff?' })
    expect(warn).toHaveTextContent('measurements are archived, not deleted')
    fireEvent.click(within(warn).getByRole('button', { name: 'Change class' }))
    expect(m.reclassifyMutate.mock.calls[0][0]).toMatchObject({ id: 'd1', doc_class: 'specification', confirm: true })
  })

  it('bulk changes the selected files by id and lists per-file failures', async () => {
    m.bulkAsync.mockResolvedValue({
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
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalled())
    const body = m.bulkAsync.mock.calls[0][0]
    expect([...body.document_ids].sort()).toEqual(['a1', 's1'])
    expect(body.filter).toBeUndefined()
    expect(body).toMatchObject({ doc_class: 'other', sub_type: null, drawing_type: null, confirm: true })
    expect(await screen.findByRole('alert')).toHaveTextContent('addendum1.pdf: Cannot route')
    expect(screen.getByText('Changed 1 of 2, failed 1')).toBeInTheDocument()
    expect(m.invalidate).toHaveBeenCalled()
  })

  it('the group checkbox selects the whole group server-side and bulk reclassify loops the cursor', async () => {
    m.bulkAsync
      .mockResolvedValueOnce({ confirmed: 2, failed: 0, skipped: 0, results: [], matched: 5, next_cursor: 'c1' })
      .mockResolvedValueOnce({ confirmed: 2, failed: 0, skipped: 0, results: [], matched: 5, next_cursor: 'c2' })
      .mockResolvedValueOnce({ confirmed: 0, failed: 1, skipped: 0, results: [{ id: 'zz', ok: false, status: null, routed_kind: null, error: 'Locked' }], matched: 5, next_cursor: null })
    renderTree({ groups: [groupCount('specification', 5)], total: 5 })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all 5 in Specification' }))
    expect(screen.getByText('All 5 in Specification selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 5 files' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalledTimes(3))
    const calls = m.bulkAsync.mock.calls.map((c) => c[0])
    expect(calls.map((c) => c.cursor)).toEqual([null, 'c1', 'c2'])
    for (const c of calls) {
      expect(c.filter).toEqual({ doc_class: 'specification' })
      expect(c.document_ids).toBeUndefined()
      expect(c).toMatchObject({ doc_class: 'other', confirm: true })
    }
    expect(await screen.findByText('Changed 4 of 5, failed 1')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('zz: Locked')
  })

  it('shows live progress and Cancel stops a group change after the current chunk', async () => {
    let release: (v: unknown) => void = () => {}
    m.bulkAsync
      .mockImplementationOnce(() => new Promise((res) => (release = res)))
      .mockResolvedValue({ confirmed: 9, failed: 0, skipped: 0, results: [], matched: 9, next_cursor: null })
    renderTree({ groups: [groupCount('specification', 9)], total: 9 })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all 9 in Specification' }))
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 9 files' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(await screen.findByText('Changed 0 of 9')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    release({ confirmed: 3, failed: 0, skipped: 0, results: [], matched: 9, next_cursor: 'c1' })
    expect(await screen.findByText('Changed 3 of 9. Stopped before the rest.')).toBeInTheDocument()
    expect(m.bulkAsync).toHaveBeenCalledTimes(1)
  })

  it('asks before a drawing group loses its drawings, but not for a group that cannot hold drawings', async () => {
    m.bulkAsync.mockResolvedValue({ confirmed: 3, failed: 0, skipped: 0, results: [], matched: 3, next_cursor: null })
    renderTree()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all 3 in Drawing' }))
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 3 files' }))
    let dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(m.bulkAsync).not.toHaveBeenCalled()
    const warn = screen.getByRole('dialog', { name: 'Take this out of the takeoff?' })
    expect(warn).toHaveTextContent('Some of the 3 files in Drawing may be drawings')
    fireEvent.click(within(warn).getByRole('button', { name: 'Change class' }))
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalledTimes(1))
    expect(m.bulkAsync.mock.calls[0][0].filter).toEqual({ doc_class: 'drawing' })

    // A specification group cannot hold drawings: no warning.
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all 1 in Specification' }))
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 1 file' }))
    dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    expect(screen.queryByRole('dialog', { name: 'Take this out of the takeoff?' })).not.toBeInTheDocument()
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalledTimes(2))
  })

  it('selects everything that matches the filters server-side', async () => {
    m.bulkAsync.mockResolvedValue({ confirmed: 1, failed: 0, skipped: 0, results: [], matched: 1, next_cursor: null })
    renderTree()
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'failed' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all 1 matching files' }))
    fireEvent.click(screen.getByRole('button', { name: 'Change class for 1 file' }))
    const dialog = screen.getByRole('dialog', { name: 'Change class' })
    fireEvent.change(within(dialog).getByLabelText('Class'), { target: { value: 'other' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply class' }))
    // Matching files may be drawings, so the leaving-the-takeoff confirm comes first.
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Take this out of the takeoff?' })).getByRole('button', { name: 'Change class' }))
    await waitFor(() => expect(m.bulkAsync).toHaveBeenCalled())
    expect(m.bulkAsync.mock.calls[0][0].filter).toEqual({ display_status: 'failed' })
  })

  it('asks for a reason before excluding', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'Exclude spec.pdf' }))
    const dialog = screen.getByRole('dialog', { name: 'Exclude spec.pdf?' })
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Superseded by addendum' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Exclude' }))
    expect(m.excludeMutate.mock.calls[0][0]).toEqual({ id: 's1', reason: 'Superseded by addendum' })
  })

  it('marks the files the latest agent run read, and only those', () => {
    m.readFiles = new Set(['b1'])
    renderTree()
    expect(rowOf('boq.xlsx').getByText('Read by agent')).toBeInTheDocument()
    expect(rowOf('spec.pdf').queryByText('Read by agent')).not.toBeInTheDocument()
    expect(screen.getAllByText('Read by agent')).toHaveLength(1)
  })

  it('shows no mark and changes nothing when there is no agent run', () => {
    renderTree()
    expect(screen.queryByText('Read by agent')).not.toBeInTheDocument()
    expect(groupNames()).toContain('Bill of quantities, 1 file')
  })

  it('also marks files in the flat search list', async () => {
    m.readFiles = new Set(['s1'])
    renderTree()
    fireEvent.change(screen.getByLabelText('Search documents'), { target: { value: 'spec' } })
    await waitFor(() => expect(screen.getByText('1 file matches')).toBeInTheDocument())
    expect(rowOf('spec.pdf').getByText('Read by agent')).toBeInTheDocument()
  })

  it('opens the evidence modal', () => {
    renderTree()
    fireEvent.click(screen.getByRole('button', { name: 'View evidence for spec.pdf' }))
    expect(screen.getByRole('dialog', { name: 'Evidence for spec.pdf' })).toBeInTheDocument()
  })

  it('is read-only without the confirm role but still offers evidence and download', () => {
    renderTree({ canConfirm: false })
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change class/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Exclude/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View evidence for spec.pdf' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download spec.pdf' })).toHaveAttribute('href', '/api/v1/tender-documents/s1/download')
  })

  it('says so when there are no documents', () => {
    renderTree({ groups: [], folders: [], total: 0 })
    expect(screen.getByText('No documents yet.')).toBeInTheDocument()
  })
})
