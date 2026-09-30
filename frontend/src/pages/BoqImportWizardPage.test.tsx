import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Role } from '../lib/roles'
import { makeExtraction, makeRow } from '../features/boq/pdf/fixtures'
import { BoqImportWizardPage } from './BoqImportWizardPage'

const get = vi.fn()
const post = vi.fn()
vi.mock('../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), put: vi.fn() },
}))

let roles: string[] = []
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

function renderPage(url = '/projects/p1/boq/import') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/boq/import" element={<BoqImportWizardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const aiOk = { provider: 'openai', external: true, configured: true, external_ai_allowed: true, available: true, message: null }
const pdf = () => new File(['pdf-bytes'], 'boq.pdf', { type: 'application/pdf' })
const fileInput = () => screen.getByLabelText(/BOQ file/)

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  roles = [Role.LEAD_ESTIMATOR]
  get.mockImplementation((path: string) => {
    if (path === '/ai/status') return Promise.resolve(aiOk)
    if (path === '/boq-pdf-extractions/x1') return Promise.resolve(makeExtraction({ rows: [makeRow()] }))
    return Promise.reject(new Error(`unexpected GET ${path}`))
  })
})

describe('BoqImportWizardPage PDF branch', () => {
  it('keeps the spreadsheet mapping UI for xlsx files', () => {
    renderPage()
    fireEvent.change(fileInput(), { target: { files: [new File(['x'], 'boq.xlsx')] } })
    expect(screen.getByLabelText('Item No column *')).toBeInTheDocument()
    expect(screen.queryByText('Use AI to read unclear or scanned pages')).not.toBeInTheDocument()
  })

  it('switches to the PDF flow, starts extraction with use_ai, and reaches the review grid', async () => {
    post.mockResolvedValue(makeExtraction({ status: 'queued', rows: [] }))
    renderPage()
    expect(fileInput()).toHaveAttribute('accept', expect.stringContaining('.pdf'))
    fireEvent.change(fileInput(), { target: { files: [pdf()] } })
    expect(screen.queryByLabelText('Item No column *')).not.toBeInTheDocument()
    const ai = screen.getByLabelText('Use AI to read unclear or scanned pages')
    expect(ai).toBeChecked()
    fireEvent.click(ai)
    fireEvent.click(screen.getByRole('button', { name: 'Read the PDF' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/projects/p1/boq-pdf-extractions')
    const fd = post.mock.calls[0][1] as FormData
    expect(fd.get('use_ai')).toBe('false')
    expect((fd.get('file') as File).name).toBe('boq.pdf')
    expect(await screen.findByRole('button', { name: 'Import 1 item' })).toBeEnabled()
  })

  it('says plainly that unclear pages are not read when AI is unavailable', async () => {
    get.mockImplementation((path: string) =>
      path === '/ai/status'
        ? Promise.resolve({ ...aiOk, available: false, message: 'AI not configured' })
        : Promise.reject(new Error('unexpected')),
    )
    renderPage()
    fireEvent.change(fileInput(), { target: { files: [pdf()] } })
    expect(await screen.findByText(/unclear or scanned pages will not be read/)).toBeInTheDocument()
  })

  it('does not let non-permitted roles start a PDF extraction', () => {
    roles = [Role.ESTIMATOR]
    renderPage()
    expect(fileInput()).toHaveAttribute('accept', expect.not.stringContaining('.pdf'))
    fireEvent.change(fileInput(), { target: { files: [pdf()] } })
    expect(screen.queryByRole('button', { name: 'Read the PDF' })).not.toBeInTheDocument()
    expect(screen.getByText(/limited to lead estimators/)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('starts from document_id for a classified PDF BOQ', async () => {
    get.mockImplementation((path: string) => {
      if (path === '/ai/status') return Promise.resolve(aiOk)
      if (path === '/tender-documents/d1') return Promise.resolve({ id: 'd1', ext: '.pdf', original_filename: 'tender.pdf' })
      if (path === '/boq-pdf-extractions/x1') return Promise.resolve(makeExtraction())
      return Promise.reject(new Error(`unexpected GET ${path}`))
    })
    post.mockResolvedValue(makeExtraction({ status: 'queued' }))
    renderPage('/projects/p1/boq/import?document=d1')
    fireEvent.click(await screen.findByRole('button', { name: 'Read the PDF' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const fd = post.mock.calls[0][1] as FormData
    expect(fd.get('document_id')).toBe('d1')
    expect(fd.get('file')).toBeNull()
    expect(get).not.toHaveBeenCalledWith('/tender-documents/d1/boq-prefill', expect.anything())
  })
})
