import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TEST_CLASSES, treeItem, treeSummary } from './testFixtures'
import type { TreeOut } from './types'

let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

let tree: TreeOut = { items: [], summary: treeSummary() }
let loading = false
const confirmMutate = vi.fn()
const reclassifyMutate = vi.fn()
const idle = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })

vi.mock('./api', () => ({
  useTenderTree: () => ({ data: loading ? undefined : tree, isLoading: loading, isError: false, error: null }),
  useTenderClasses: () => ({ data: TEST_CLASSES }),
  useTenderPackages: () => ({ data: [] }),
  useTenderDocument: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectAddenda: () => ({ data: [], isLoading: false, isError: false }),
  useDocumentRegister: () => ({ data: { items: [], total: 0, limit: 50, offset: 0 }, isLoading: false, isError: false }),
  useCreateTenderPackage: () => idle(),
  useAddTenderFiles: () => idle(),
  useConfirmDocument: () => ({ mutate: confirmMutate, isPending: false }),
  useReclassifyDocument: () => ({ mutate: reclassifyMutate, isPending: false }),
  useBulkConfirm: () => idle(),
  useBulkReclassify: () => idle(),
  useExclude: () => idle(),
  useRerun: () => idle(),
}))

import { ProjectDocuments } from './ProjectDocuments'

const renderPanel = () =>
  render(
    <MemoryRouter>
      <ProjectDocuments projectId="p1" />
    </MemoryRouter>,
  )

const needsCheck = (name: string) => treeItem({ name, doc_class: 'specification', display_status: 'needs_check', status: 'proposed', confidence: 0.6 })

describe('ProjectDocuments', () => {
  beforeEach(() => {
    roles = ['lead_estimator']
    tree = { items: [], summary: treeSummary() }
    loading = false
    confirmMutate.mockReset()
    reclassifyMutate.mockReset()
  })

  it('shows a skeleton while the tree loads', () => {
    loading = true
    renderPanel()
    expect(screen.queryByText('Drop your tender folder or zip here')).not.toBeInTheDocument()
  })

  it('an empty project shows the hero drop zone with folder and files buttons', () => {
    renderPanel()
    expect(screen.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose folder' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeInTheDocument()
    expect(screen.getByText('Upload details')).toBeInTheDocument()
    expect(screen.queryByText('Next steps')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add more files' })).not.toBeInTheDocument()
  })

  it('an empty project shows no upload to a role that cannot upload', () => {
    roles = ['viewer']
    renderPanel()
    expect(screen.queryByRole('button', { name: 'Choose folder' })).not.toBeInTheDocument()
    expect(screen.getByText(/No tender documents have been uploaded yet/)).toBeInTheDocument()
  })

  it('shows the live progress bar while files are being read', () => {
    tree = {
      items: [treeItem({ doc_class: 'drawing', display_status: 'ready' }), treeItem({ display_status: 'reading' }), treeItem({ display_status: 'queued' })],
      summary: treeSummary({ total: 10, in_progress: 4, by_display_status: { reading: 3, queued: 1, ready: 6 } }),
    }
    renderPanel()
    expect(screen.getByText('Reading documents: 6 of 10')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Documents read' })
    expect(bar).toHaveAttribute('aria-valuenow', '6')
    expect(bar).toHaveAttribute('aria-valuemax', '10')
    expect(screen.getByText(/Reading:/)).toBeInTheDocument()
    expect(screen.getByText(/Queued:/)).toBeInTheDocument()
  })

  it('shows no progress bar once everything is read', () => {
    tree = { items: [treeItem({ doc_class: 'other' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('shows the AI-unavailable notice using the server message', () => {
    tree = {
      items: [treeItem({ doc_class: 'other', flags: ['rules_fallback'], decided_by: 'rules' })],
      summary: treeSummary({ total: 1, ai_available: false, ai_message: 'AI is unavailable, so files are classified by the built-in rules and need your check.' }),
    }
    renderPanel()
    expect(screen.getByText('AI classification is off')).toBeInTheDocument()
    expect(screen.getByText(/AI is unavailable, so files are classified by the built-in rules/)).toBeInTheDocument()
    expect(screen.getByText('Classified by rules')).toBeInTheDocument()
  })

  it('has no AI notice when AI is available', () => {
    tree = { items: [treeItem({ doc_class: 'other' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    expect(screen.queryByText('AI classification is off')).not.toBeInTheDocument()
  })

  it('puts Needs your check above the tree, and Confirm routes the file', () => {
    const item = needsCheck('maybe-spec.pdf')
    tree = { items: [item, treeItem({ doc_class: 'other', name: 'fine.pdf' })], summary: treeSummary({ total: 2, needs_check: 1 }) }
    renderPanel()
    const needs = screen.getByRole('heading', { name: 'Needs your check (1)' })
    const treeHeading = screen.getByRole('heading', { name: 'Project documents' })
    expect(needs.compareDocumentPosition(treeHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm maybe-spec.pdf' }))
    expect(confirmMutate.mock.calls[0][0]).toBe(item.id)
  })

  it('an estimator sees the needs-check list read-only', () => {
    roles = ['estimator']
    tree = { items: [needsCheck('maybe-spec.pdf')], summary: treeSummary({ total: 1, needs_check: 1 }) }
    renderPanel()
    const list = screen.getByRole('list', { name: 'Files that need your check' })
    expect(within(list).getByText('maybe-spec.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Confirm/ })).not.toBeInTheDocument()
    expect(screen.getByText(/need a lead estimator or above/)).toBeInTheDocument()
  })

  it('hides Needs your check when nothing needs checking', () => {
    tree = { items: [treeItem({ doc_class: 'other' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    expect(screen.queryByText(/Needs your check/)).not.toBeInTheDocument()
  })

  it('enables the next steps that are possible and explains the ones that are not', () => {
    const boq = treeItem({ name: 'boq.xlsx', doc_class: 'boq' })
    const drawing = treeItem({ name: 'C-1.pdf', doc_class: 'drawing', drawing_id: 'dr9', routed_kind: 'drawing' })
    tree = { items: [boq, drawing], summary: treeSummary({ total: 2, boq_documents: [boq.id], drawings_total: 4, drawings_ready: 1 }) }
    renderPanel()
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('href', `/projects/p1/boq/import?document=${boq.id}`)
    expect(screen.getByRole('link', { name: 'Open drawings / takeoff' })).toHaveAttribute('href', '/projects/p1/drawings/dr9')
    expect(screen.getByText('1 of 4 drawings ready')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Run verification report' })).toHaveAttribute('href', '/projects/p1/verification')
    expect(screen.getByRole('link', { name: 'Build settlement' })).toHaveAttribute('href', '/projects/p1/settlement')
  })

  it('disables Import BOQ and Open drawings with a reason when there is nothing to open', () => {
    tree = { items: [treeItem({ doc_class: 'specification' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    expect(screen.getByText(/No BOQ has been found yet/)).toBeInTheDocument()
    expect(screen.getByText('No drawings yet.')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Import BOQ' })[0]).toHaveAttribute('aria-disabled', 'true')
  })

  it('lets the user pick between several BOQ documents', () => {
    const a = treeItem({ name: 'boq-a.xlsx', doc_class: 'boq' })
    const b = treeItem({ name: 'boq-b.xlsx', doc_class: 'boq' })
    tree = { items: [a, b], summary: treeSummary({ total: 2, boq_documents: [a.id, b.id] }) }
    renderPanel()
    fireEvent.change(screen.getByLabelText('BOQ document'), { target: { value: b.id } })
    expect(screen.getByRole('link', { name: 'Import BOQ' })).toHaveAttribute('href', `/projects/p1/boq/import?document=${b.id}`)
  })

  it('keeps the registers collapsed until opened', () => {
    tree = { items: [treeItem({ doc_class: 'other' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    const toggle = screen.getByRole('button', { name: /Registers/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Addenda register')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByText('Addenda register')).toBeInTheDocument()
    expect(screen.getByText('Project document register')).toBeInTheDocument()
  })

  it('offers Add more files once documents exist', () => {
    tree = { items: [treeItem({ doc_class: 'other' })], summary: treeSummary({ total: 1 }) }
    renderPanel()
    const toggle = screen.getByRole('button', { name: /Add more files/ })
    fireEvent.click(toggle)
    expect(screen.getByText('Upload tender documents')).toBeVisible()
  })
})
