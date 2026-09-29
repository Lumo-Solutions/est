import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TenderDocument } from './types'

let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const bulkMutate = vi.fn()
const docs: TenderDocument[] = [
  doc({ id: 'd1', original_filename: 'plan-a.pdf', doc_class: 'drawing', confidence: 0.92, flags: ['duplicate'], status: 'proposed' }),
  doc({ id: 'd2', original_filename: 'boq.xlsx', doc_class: 'boq', confidence: 0.4, flags: ['low_confidence', 'conflict'], status: 'proposed' }),
]

function doc(over: Partial<TenderDocument>): TenderDocument {
  return {
    id: 'x', project_id: 'p1', package_id: 'pk1', parent_document_id: null, archive_path: null, original_filename: 'f.pdf', ext: 'pdf',
    sha256: '', size_bytes: 1, content_type_sniffed: null, safety_status: 'ok', rejection_reason: null, doc_class: null, sub_type: null,
    confidence: null, title: null, document_number: null, revision_label: null, metadata: {}, evidence: [], flags: [], status: 'proposed',
    error_message: null, duplicate_of_id: null, supersedes_id: null, routed_kind: null, routed_ref: {}, confirmed_by: null,
    confirmed_at: null, created_at: '2026-01-01T00:00:00Z', ...over,
  }
}

const idle = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })

vi.mock('./api', () => ({
  useTenderPackages: () => ({ data: [{ id: 'pk1', project_id: 'p1', label: 'Transmittal 1', transmittal_ref: null, received_date: '2026-01-01', status: 'processed', file_count: 2, created_at: '' }] }),
  useTenderClasses: () => ({ data: [
    { code: 'drawing', label: 'Drawing', default_label: 'Drawing', enabled: true, sort_order: 1 },
    { code: 'boq', label: 'Bill of quantities', default_label: 'BOQ', enabled: true, sort_order: 2 },
  ] }),
  useTenderDocuments: () => ({ data: { items: docs, total: 2, limit: 100, offset: 0 }, isLoading: false, isError: false }),
  useTenderDocument: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectAddenda: () => ({ data: [], isLoading: false, isError: false }),
  useDocumentRegister: () => ({ data: { items: [], total: 0, limit: 50, offset: 0 }, isLoading: false, isError: false }),
  useCreateTenderPackage: () => idle(),
  useAddTenderFiles: () => idle(),
  useConfirmDocument: () => idle(),
  useReclassify: () => idle(),
  useEditMetadata: () => idle(),
  useExclude: () => idle(),
  useRerun: () => idle(),
  useBulkConfirm: () => ({ mutate: bulkMutate, mutateAsync: vi.fn(), isPending: false }),
}))

import { TenderDocumentsTab } from './TenderDocumentsTab'

function renderTab() {
  return render(
    <MemoryRouter>
      <TenderDocumentsTab projectId="p1" />
    </MemoryRouter>,
  )
}

describe('TenderDocumentsTab', () => {
  beforeEach(() => {
    bulkMutate.mockReset()
  })

  it('renders rows with class label, confidence and flags', async () => {
    roles = ['lead_estimator']
    renderTab()
    expect(await screen.findByText('plan-a.pdf')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()
    // Scoped to the grid: the flag filter select also lists these words.
    const grid = within(document.querySelector('.ag-root-wrapper') as HTMLElement)
    expect(grid.getByText('Duplicate')).toBeInTheDocument()
    expect(grid.getByText('Low confidence')).toBeInTheDocument()
    expect(grid.getByText('Conflict')).toBeInTheDocument()
    expect(screen.getByLabelText('Class for plan-a.pdf')).toHaveValue('drawing')
    expect(screen.getByText('Showing 1 to 2 of 2')).toBeInTheDocument()
  })

  it('lead sees Confirm, Exclude and Re-run; estimator sees none but can upload', async () => {
    roles = ['lead_estimator']
    const { unmount } = renderTab()
    expect(await screen.findByRole('button', { name: 'Confirm plan-a.pdf' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Exclude plan-a.pdf' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Re-run plan-a.pdf' })).toBeInTheDocument()
    unmount()

    roles = ['estimator']
    renderTab()
    expect(await screen.findByText('plan-a.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Confirm / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Exclude / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Re-run / })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Confirm high-confidence' })).toBeNull()
    expect(screen.getByTestId('tender-file-input')).toBeInTheDocument()
  })

  it('hides the upload panel for a role without upload rights', async () => {
    roles = ['platform_admin']
    renderTab()
    expect(await screen.findByText('plan-a.pdf')).toBeInTheDocument()
    expect(screen.queryByTestId('tender-file-input')).toBeNull()
  })

  it('shows the bulk-confirm result message and failed items', async () => {
    roles = ['lead_estimator']
    bulkMutate.mockImplementation((_body, opts) =>
      opts.onSuccess({
        confirmed: 3,
        skipped: 2,
        failed: 1,
        results: [{ id: 'd2', ok: false, status: 'proposed', routed_kind: null, error: 'could not route' }],
      }),
    )
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm high-confidence' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all' }))
    await waitFor(() => expect(bulkMutate).toHaveBeenCalledWith({}, expect.anything()))
    expect(screen.getByRole('status')).toHaveTextContent('Confirmed 3, skipped 2, failed 1')
    expect(screen.getByRole('alert')).toHaveTextContent('boq.xlsx: could not route')
  })
})
