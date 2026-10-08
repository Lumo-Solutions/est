import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, groupCount, packageProgress, treeItem, treeOut, treeSummary } from './testFixtures'
import type { DocFilter, TreeItem, TreeOut } from './types'

const m = vi.hoisted(() => ({
  roles: [] as string[],
  tree: null as unknown,
  loading: false,
  needsRows: [] as unknown[],
  itemsCalls: [] as (DocFilter | null)[],
  confirmMutate: vi.fn(),
  pauseMutate: vi.fn(),
}))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => m.roles.includes(x)) }),
}))
vi.mock('../drawings/MeasureAll', () => ({ MeasureAll: ({ projectId }: { projectId: string }) => <div data-testid="measure-all">{projectId}</div> }))
// The upload panel is the other half of the intake work; here it only needs to show where it is placed.
vi.mock('./UploadPanel', () => ({
  UploadPanel: ({ variant }: { variant?: string }) => <div data-testid={`upload-${variant ?? 'inline'}`}>Upload panel</div>,
}))

const idle = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })
vi.mock('./api', () => ({
  useTenderTree: () => ({ data: m.loading ? undefined : m.tree, isLoading: m.loading, isError: false, error: null }),
  useTenderItems: (_p: string, filter: DocFilter | null) => {
    m.itemsCalls.push(filter)
    const base = { isLoading: false, isError: false, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn() }
    if (filter?.has_class) return { ...base, data: { pages: [{ items: [], total: m.needsRows.length, limit: 1, offset: 0 }] } }
    if (filter?.display_status === 'needs_check') return { ...base, data: { pages: [{ items: m.needsRows, total: m.needsRows.length, limit: 25, offset: 0 }] } }
    return { ...base, data: { pages: [{ items: [], total: 0, limit: 100, offset: 0 }] } }
  },
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useTenderPackages: () => ({ data: [] }),
  useTenderDocument: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectAddenda: () => ({ data: [], isLoading: false, isError: false }),
  useDocumentRegister: () => ({ data: { items: [], total: 0, limit: 50, offset: 0 }, isLoading: false, isError: false }),
  useInvalidateIntake: () => vi.fn(),
  useConfirmDocument: () => ({ mutate: m.confirmMutate, isPending: false }),
  useReclassifyDocument: () => idle(),
  useBulkConfirm: () => idle(),
  useBulkReclassify: () => idle(),
  useExclude: () => idle(),
  useRerun: () => idle(),
  usePauseTenderPackage: () => ({ mutate: m.pauseMutate, isPending: false }),
  useResumeTenderPackage: () => idle(),
  useCancelTenderPackage: () => idle(),
}))

import { ProjectDocuments } from './ProjectDocuments'

const setTree = (t: TreeOut) => {
  m.tree = t
}
const renderPanel = () =>
  render(
    <MemoryRouter>
      <ProjectDocuments projectId="p1" />
    </MemoryRouter>,
  )

const needsCheck = (name: string): TreeItem =>
  treeItem({ name, doc_class: 'specification', display_status: 'needs_check', status: 'proposed', confidence: 0.6 })

describe('ProjectDocuments', () => {
  beforeEach(() => {
    m.roles = ['lead_estimator']
    setTree(treeOut())
    m.loading = false
    m.needsRows = []
    m.itemsCalls = []
    m.confirmMutate.mockReset()
    m.pauseMutate.mockReset()
  })

  it('shows a skeleton while the tree loads', () => {
    m.loading = true
    renderPanel()
    expect(screen.queryByTestId('upload-hero')).not.toBeInTheDocument()
  })

  it('an empty project shows the hero drop zone and nothing else', () => {
    renderPanel()
    expect(screen.getByTestId('upload-hero')).toBeInTheDocument()
    expect(screen.queryByText('Next steps')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add more files/ })).not.toBeInTheDocument()
  })

  it('places the measure-all card below the next steps once there are documents, not for an empty project', () => {
    renderPanel()
    expect(screen.queryByTestId('measure-all')).not.toBeInTheDocument()
    setTree(treeOut({ summary: treeSummary({ total: 1 }), groups: [groupCount('other', 1)] }))
    renderPanel()
    expect(screen.getByTestId('measure-all')).toHaveTextContent('p1')
  })

  it('an empty project shows no upload to a role that cannot upload', () => {
    m.roles = ['viewer']
    renderPanel()
    expect(screen.queryByTestId('upload-hero')).not.toBeInTheDocument()
    expect(screen.getByText(/No tender documents have been uploaded yet/)).toBeInTheDocument()
  })

  it('is not empty while files are still arriving or a pack is being unpacked', () => {
    setTree(treeOut({ summary: treeSummary({ total: 0, pending_upload: 40 }), packages: [packageProgress({ status: 'uploading', expected_count: 100, uploaded: 60, registered: 100, pending_upload: 40 })] }))
    renderPanel()
    expect(screen.queryByTestId('upload-hero')).not.toBeInTheDocument()
    expect(screen.getByText('Uploaded 60 of 100 files')).toBeInTheDocument()
    expect(screen.getByText('Next steps')).toBeInTheDocument()
  })

  it('shows the live progress bar while files are being read, from the summary', () => {
    setTree(treeOut({ summary: treeSummary({ total: 10, in_progress: 4, by_display_status: { reading: 3, queued: 1, ready: 6 } }), groups: [groupCount('other', 10)] }))
    renderPanel()
    expect(screen.getByText('Reading documents: 6 of 10')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Documents read' })).toHaveAttribute('aria-valuenow', '6')
  })

  it('shows no progress bar once everything is read', () => {
    setTree(treeOut({ summary: treeSummary({ total: 1 }), groups: [groupCount('other', 1)] }))
    renderPanel()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('shows the AI-unavailable notice using the server message', () => {
    setTree(treeOut({ summary: treeSummary({ total: 1, ai_available: false, ai_message: 'AI is unavailable, so files are classified by the built-in rules and need your check.' }), groups: [groupCount('other', 1)] }))
    renderPanel()
    expect(screen.getByText('AI classification is off')).toBeInTheDocument()
    expect(screen.getByText(/AI is unavailable, so files are classified by the built-in rules/)).toBeInTheDocument()
  })

  it('builds the tree from counts only and puts Needs your check above it; Confirm routes the file', () => {
    const item = needsCheck('maybe-spec.pdf')
    m.needsRows = [item]
    setTree(treeOut({ summary: treeSummary({ total: 2, needs_check: 1 }), groups: [groupCount('specification', 1), groupCount('other', 1)] }))
    expect(m.tree).not.toHaveProperty('items')
    renderPanel()
    const needs = screen.getByRole('heading', { name: 'Needs your check (1)' })
    const treeHeading = screen.getByRole('heading', { name: 'Project documents' })
    expect(needs.compareDocumentPosition(treeHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Specification, 1 file' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm maybe-spec.pdf' }))
    expect(m.confirmMutate.mock.calls[0][0]).toBe(item.id)
  })

  it('an estimator sees the needs-check list read-only', () => {
    m.roles = ['estimator']
    m.needsRows = [needsCheck('maybe-spec.pdf')]
    setTree(treeOut({ summary: treeSummary({ total: 1, needs_check: 1 }), groups: [groupCount('specification', 1)] }))
    renderPanel()
    const list = screen.getByRole('list', { name: 'Files that need your check' })
    expect(within(list).getByText('maybe-spec.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Confirm/ })).not.toBeInTheDocument()
    expect(screen.getByText(/need a lead estimator or above/)).toBeInTheDocument()
  })

  it('hides Needs your check when nothing needs checking', () => {
    setTree(treeOut({ summary: treeSummary({ total: 1 }), groups: [groupCount('other', 1)] }))
    renderPanel()
    expect(screen.queryByText(/Needs your check/)).not.toBeInTheDocument()
  })

  it('enables the next steps that are possible, from the summary alone', () => {
    setTree(
      treeOut({
        summary: treeSummary({ total: 2, boq_documents: [{ id: 'b1', name: 'boq.xlsx' }], first_drawing_id: 'dr9', drawings_total: 4, drawings_ready: 1 }),
        groups: [groupCount('boq', 1), groupCount('drawing', 1, 'roads_civil', 'plan_profile')],
      }),
    )
    renderPanel()
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('href', '/projects/p1/boq/import?document=b1')
    expect(screen.getByRole('link', { name: 'Open drawings / takeoff' })).toHaveAttribute('href', '/projects/p1/drawings/dr9')
    expect(screen.getByText('1 of 4 drawings ready')).toBeInTheDocument()
  })

  it('keeps the registers collapsed until opened', () => {
    setTree(treeOut({ summary: treeSummary({ total: 1 }), groups: [groupCount('other', 1)] }))
    renderPanel()
    const toggle = screen.getByRole('button', { name: /Registers/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Addenda register')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByText('Addenda register')).toBeInTheDocument()
  })

  it('offers Add more files, closed, once documents exist', () => {
    setTree(treeOut({ summary: treeSummary({ total: 1 }), groups: [groupCount('other', 1)] }))
    renderPanel()
    const toggle = screen.getByRole('button', { name: /Add more files/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('upload-inline')).toBeVisible()
  })

  it('opens Add more files by itself when a pack is still uploading, so resuming is one click away', () => {
    setTree(
      treeOut({
        summary: treeSummary({ total: 30 }),
        groups: [groupCount('other', 30)],
        packages: [packageProgress({ status: 'uploading', expected_count: 100, registered: 30, uploaded: 30, pending_upload: 0 })],
      }),
    )
    renderPanel()
    expect(screen.getByRole('button', { name: /Add more files/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/This upload was not finished \(30 of 100 files arrived\)/)).toBeInTheDocument()
  })

  it('shows pack Pause / Cancel to a lead estimator only', () => {
    setTree(treeOut({ summary: treeSummary({ total: 5, packages_processing: 1, in_progress: 2 }), groups: [groupCount('other', 5)], packages: [packageProgress({ status: 'processing' })] }))
    const { unmount } = renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Pause Transmittal 1' }))
    expect(m.pauseMutate.mock.calls[0][0]).toBe('pk1')
    expect(screen.getByRole('button', { name: 'Cancel Transmittal 1' })).toBeInTheDocument()
    unmount()

    m.roles = ['estimator']
    renderPanel()
    expect(screen.queryByRole('button', { name: /^Pause/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel/ })).not.toBeInTheDocument()
  })
})
