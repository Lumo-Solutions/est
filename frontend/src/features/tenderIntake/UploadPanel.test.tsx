import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const createAsync = vi.fn()
const addAsync = vi.fn()
vi.mock('./api', () => ({
  useCreateTenderPackage: () => ({ mutateAsync: createAsync }),
  useAddTenderFiles: () => ({ mutateAsync: addAsync }),
}))

import { UploadPanel } from './UploadPanel'

function pdf(name: string): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

function chooseFiles(files: File[]) {
  fireEvent.change(screen.getByTestId('tender-file-input'), { target: { files } })
}

describe('UploadPanel resumable upload', () => {
  beforeEach(() => {
    createAsync.mockReset()
    addAsync.mockReset()
  })

  it('creates the package with the first batch and adds the rest to it', async () => {
    createAsync.mockResolvedValue({ package_id: 'pk1' })
    addAsync.mockResolvedValue({ package_id: 'pk1' })
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} />)
    chooseFiles(Array.from({ length: 45 }, (_, i) => pdf(`f${i}.pdf`)))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 45 files' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('pk1'))
    expect(createAsync).toHaveBeenCalledTimes(1)
    expect(createAsync.mock.calls[0][0].files).toHaveLength(20)
    expect(addAsync.mock.calls.map((c) => [c[0].files.length, c[0].packageId])).toEqual([[20, 'pk1'], [5, 'pk1']])
    expect(screen.getByRole('status')).toHaveTextContent('Uploaded 45 of 45 files')
  })

  it('after a failed batch keeps only the unsent files and continues in the same package', async () => {
    createAsync.mockResolvedValue({ package_id: 'pk1' })
    addAsync.mockRejectedValueOnce(new Error('Request failed (502)')).mockResolvedValue({ package_id: 'pk1' })
    const onUploaded = vi.fn()
    render(<UploadPanel projectId="p1" onUploaded={onUploaded} />)
    chooseFiles(Array.from({ length: 45 }, (_, i) => pdf(`f${i}.pdf`)))
    fireEvent.click(screen.getByRole('button', { name: 'Upload 45 files' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Request failed (502)')
    expect(alert).toHaveTextContent('20 of 45 files were uploaded; 25 still to send')
    expect(onUploaded).not.toHaveBeenCalled()
    // Only the unsent files are left in the list, and the button says so.
    fireEvent.click(await screen.findByRole('button', { name: 'Upload 25 files' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('pk1'))
    expect(createAsync).toHaveBeenCalledTimes(1) // no second package
    expect(addAsync.mock.calls.at(-1)?.[0]).toMatchObject({ packageId: 'pk1' })
    const sent = addAsync.mock.calls.slice(1).flatMap((c) => c[0].files.map((f: File) => f.name))
    expect(sent).toEqual(Array.from({ length: 25 }, (_, i) => `f${i + 20}.pdf`))
    expect(screen.getByRole('status')).toHaveTextContent('Uploaded 45 of 45 files')
  })

  it('rejects a file over the per-file limit without adding it', () => {
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    const big = new File(['x'], 'huge.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: 61 * 1024 * 1024 })
    chooseFiles([big, pdf('ok.pdf')])
    expect(screen.getByRole('alert')).toHaveTextContent('huge.pdf')
    expect(screen.getByRole('button', { name: 'Upload 1 file' })).toBeInTheDocument()
  })

  it('shows the relative path next to the file and passes the pathed file on', async () => {
    createAsync.mockResolvedValue({ package_id: 'pk1' })
    render(<UploadPanel projectId="p1" onUploaded={vi.fn()} />)
    const f = Object.assign(pdf('C-101.pdf'), { relativePath: 'Tender Package/Drawings/C-101.pdf' })
    chooseFiles([f, pdf('plain.pdf')])
    expect(screen.getByText('Tender Package/Drawings/C-101.pdf')).toBeInTheDocument()
    expect(screen.getByText('plain.pdf')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 files' }))
    await waitFor(() => expect(createAsync).toHaveBeenCalled())
    expect((createAsync.mock.calls[0][0].files[0] as { relativePath?: string }).relativePath).toBe('Tender Package/Drawings/C-101.pdf')
  })
})

describe('tender upload FormData', () => {
  it('carries the relative path as the multipart filename, falling back to the file name', async () => {
    const post = vi.fn().mockResolvedValue({ package_id: 'pk1' })
    vi.resetModules()
    vi.doMock('../../lib/api', () => ({ api: { post } }))
    const real = await vi.importActual<typeof import('./api')>('./api')
    const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
    const { renderHook } = await import('@testing-library/react')
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
    )
    const pathed = Object.assign(pdf('C-101.pdf'), { relativePath: 'Tender Package/Drawings/C-101.pdf' })
    const { result } = renderHook(() => real.useCreateTenderPackage('p1'), { wrapper })
    await result.current.mutateAsync({ files: [pathed, pdf('plain.pdf')] })
    const fd = post.mock.calls[0][1] as FormData
    const sent = fd.getAll('files') as File[]
    expect(sent.map((x) => x.name)).toEqual(['Tender Package/Drawings/C-101.pdf', 'plain.pdf'])
  })
})
