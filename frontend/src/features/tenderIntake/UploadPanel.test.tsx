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
})
