import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api'

const registerFiles = vi.fn()
const putDocumentContent = vi.fn()
vi.mock('./uploadApi', () => ({
  registerFiles: (...a: unknown[]) => registerFiles(...a),
  putDocumentContent: (...a: unknown[]) => putDocumentContent(...a),
}))

import { UploadPanel } from './UploadPanel'

function pdf(name: string): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

function chooseFiles(files: File[]) {
  fireEvent.change(screen.getByTestId('tender-file-input'), { target: { files } })
}

const names = (n: number) => Array.from({ length: n }, (_, i) => `f${i}.pdf`)

type Batch = { files: { path: string; sha256: string }[] }

// Echo every registered file back as "send me the bytes".
function acceptAll(resumed = false) {
  registerFiles.mockImplementation(async (_p: string, body: Batch) => ({
    package_id: 'pk1',
    status: 'uploading',
    resumed,
    expected_count: null,
    files: body.files.map((f) => ({ path: f.path, sha256: f.sha256, document_id: `d-${f.path}`, state: 'pending', upload: true, reason: null })),
  }))
}

function uploadedResult(documentId: string, uploaded: number) {
  return { document_id: documentId, state: 'uploaded', package_status: 'uploading', registered: uploaded, uploaded, expected_count: null }
}

describe('UploadPanel resumable upload', () => {
  beforeEach(() => {
    registerFiles.mockReset()
    putDocumentContent.mockReset()
  })

  it('shows a bounded preview for 1,600 files, not one row each', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    chooseFiles(names(1600).map(pdf))
    expect(screen.getByText(/1,600 files \(.*\) ready/)).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Files to upload' })).getAllByRole('listitem')
    expect(rows.length).toBeLessThanOrEqual(11)
    expect(screen.getByText('and 1,590 more')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload 1,600 files' })).toBeInTheDocument()
  })

  it('registers, uploads each file, shows progress and reports the package', async () => {
    acceptAll()
    let n = 0
    putDocumentContent.mockImplementation(async (_pk: string, docId: string) => uploadedResult(docId, ++n))
    const onUploaded = vi.fn()
    const onUploadStart = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} onUploadStart={onUploadStart} />)
    chooseFiles(names(3).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 3 files' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('pk1'))
    expect(onUploadStart).toHaveBeenCalledTimes(1)
    expect(registerFiles.mock.calls[0][1]).toMatchObject({ total_files: 3, package_id: null })
    expect(registerFiles.mock.calls[0][1].files[0]).toMatchObject({ path: 'f0.pdf', size: 8 })
    expect(putDocumentContent).toHaveBeenCalledTimes(3)
    expect(screen.getByRole('status')).toHaveTextContent('Uploaded 3 / 3')
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '100')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('shows progress while uploading and Stop aborts with a resume hint', async () => {
    acceptAll()
    putDocumentContent.mockImplementation(
      (_pk: string, _d: string, _f: File, signal: AbortSignal) =>
        new Promise((_res, rej) => signal.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError')))),
    )
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} />)
    chooseFiles(names(5).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 5 files' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Uploaded 0 / 5'))
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Drop the same folder again'))
    expect(onUploaded).not.toHaveBeenCalled()
    // The files are kept so the same button continues.
    expect(screen.getByRole('button', { name: 'Upload 5 files' })).toBeEnabled()
  })

  it('shows the server message when the folder is over the pack limit', async () => {
    registerFiles.mockRejectedValue(
      new ApiError(422, { type: 'about:blank', title: 'Unprocessable', status: 422, detail: 'This folder has 3,500 files; one pack holds at most 3,000.' }),
    )
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} />)
    chooseFiles(names(2).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 files' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('one pack holds at most 3,000')
    expect(onUploaded).not.toHaveBeenCalled()
    expect(putDocumentContent).not.toHaveBeenCalled()
  })

  it('shows a resumed notice and only sends the files the server lacks', async () => {
    registerFiles.mockImplementation(async (_p: string, body: Batch) => ({
      package_id: 'pk1',
      status: 'uploading',
      resumed: true,
      expected_count: 3,
      files: body.files.map((f, i) => ({
        path: f.path,
        sha256: f.sha256,
        document_id: `d-${f.path}`,
        state: i < 2 ? 'uploaded' : 'pending',
        upload: i >= 2,
        reason: null,
      })),
    }))
    putDocumentContent.mockImplementation(async (_pk: string, docId: string) => uploadedResult(docId, 3))
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} />)
    chooseFiles(names(3).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 3 files' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('pk1'))
    expect(screen.getByRole('status')).toHaveTextContent('Continuing an unfinished upload: 2 files were already here.')
    expect(putDocumentContent).toHaveBeenCalledTimes(1)
  })

  it('lists rejected files (capped) and failed files with their message', async () => {
    registerFiles.mockImplementation(async (_p: string, body: Batch) => ({
      package_id: 'pk1',
      status: 'uploading',
      resumed: false,
      expected_count: null,
      files: body.files.map((f, i) => ({
        path: f.path,
        sha256: f.sha256,
        document_id: i < 60 ? null : `d-${f.path}`,
        state: i < 60 ? 'rejected' : 'pending',
        upload: i >= 60,
        reason: i < 60 ? 'Not a tender file type' : null,
      })),
    }))
    putDocumentContent.mockRejectedValue(new ApiError(422, { type: 'about:blank', title: 'x', status: 422, detail: 'Digest does not match' }))
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    chooseFiles(names(61).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 61 files' }))
    const summary = await screen.findByText('60 files were not accepted')
    const details = summary.closest('details') as HTMLElement
    expect(within(details).getAllByRole('listitem')).toHaveLength(51)
    expect(within(details).getByText('and 10 more')).toBeInTheDocument()
    expect(await screen.findByText('f60.pdf: Digest does not match')).toBeInTheDocument()
  })

  it('rejects a file over the per-file limit without adding it', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    const big = new File(['x'], 'huge.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: 251 * 1024 * 1024 })
    chooseFiles([big, pdf('ok.pdf')])
    expect(screen.getByRole('alert')).toHaveTextContent('huge.pdf is 251.0 MB: larger than the 250 MB per-file limit')
    expect(screen.getByRole('button', { name: 'Upload 1 file' })).toBeInTheDocument()
  })

  it('shows the relative path next to the file and registers it', async () => {
    acceptAll()
    putDocumentContent.mockImplementation(async (_pk: string, docId: string) => uploadedResult(docId, 1))
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    const f = Object.assign(pdf('C-101.pdf'), { relativePath: 'Tender Package/Drawings/C-101.pdf' })
    chooseFiles([f, pdf('plain.pdf')])
    expect(screen.getByText('Tender Package/Drawings/C-101.pdf')).toBeInTheDocument()
    expect(screen.getByText('plain.pdf')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 files' }))
    await waitFor(() => expect(registerFiles).toHaveBeenCalled())
    expect(registerFiles.mock.calls[0][1].files.map((x: { path: string }) => x.path)).toEqual(['Tender Package/Drawings/C-101.pdf', 'plain.pdf'])
  })
})

describe('UploadPanel hero variant', () => {
  it('shows the big drop target with choose buttons and folds the detail fields away', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} variant="hero" />)
    expect(screen.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose folder' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeInTheDocument()
    const details = screen.getByText('Upload details').closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details).toContainElement(screen.getByLabelText('Label'))
  })

  it('the choose buttons open the drop zone inputs', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} variant="hero" />)
    const fileClick = vi.spyOn(screen.getByTestId('tender-file-input') as HTMLInputElement, 'click')
    const folderClick = vi.spyOn(screen.getByTestId('tender-folder-input') as HTMLInputElement, 'click')
    fireEvent.click(screen.getByRole('button', { name: 'Choose files' }))
    fireEvent.click(screen.getByRole('button', { name: 'Choose folder' }))
    expect(fileClick).toHaveBeenCalledTimes(1)
    expect(folderClick).toHaveBeenCalledTimes(1)
  })

  it('uploads through the same resumable flow as the compact panel', async () => {
    registerFiles.mockReset()
    putDocumentContent.mockReset()
    acceptAll()
    putDocumentContent.mockImplementation(async (_pk: string, docId: string) => uploadedResult(docId, 1))
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} variant="hero" />)
    chooseFiles(names(2).map(pdf))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 files' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('pk1'))
  })

  it('the compact variant keeps the fields visible', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    expect(screen.getByLabelText('Label')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Choose folder' })).not.toBeInTheDocument()
  })
})
