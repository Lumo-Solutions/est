import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mutateAsync = vi.fn()
vi.mock('./api', async () => {
  const { useMutation } = await import('@tanstack/react-query')
  return {
    useUploadDrawings: () =>
      useMutation({ mutationFn: (files: File[]) => mutateAsync(files) }),
  }
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ACCEPTED_DRAWING_TYPES_TEXT, DrawingUpload } from './DrawingUpload'

function renderUpload() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <DrawingUpload projectId="p1" />
    </QueryClientProvider>,
  )
}

const file = (name: string, type = '') => new File(['x'], name, { type })

describe('DrawingUpload', () => {
  beforeEach(() => mutateAsync.mockReset())

  it('states the accepted types and lets the picker take several files including .dwg', () => {
    renderUpload()
    expect(ACCEPTED_DRAWING_TYPES_TEXT).toBe('PDF (vector), DXF, DWG (auto-converted)')
    expect(screen.getByText(/PDF \(vector\), DXF, DWG \(auto-converted\)/)).toBeInTheDocument()
    const input = screen.getByTestId('drawing-file-input') as HTMLInputElement
    expect(input.multiple).toBe(true)
    expect(input.accept.split(',')).toEqual(expect.arrayContaining(['.pdf', '.dxf', '.dwg']))
  })

  it('uploads every chosen file in one batch and reports the count', async () => {
    mutateAsync.mockResolvedValue([
      { filename: 'a.dwg', ok: true },
      { filename: 'b.dxf', ok: true },
      { filename: 'c.pdf', ok: true },
    ])
    renderUpload()
    fireEvent.change(screen.getByTestId('drawing-file-input'), {
      target: { files: [file('a.dwg'), file('b.dxf'), file('c.pdf', 'application/pdf')] },
    })
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1))
    expect(mutateAsync.mock.calls[0][0].map((f: File) => f.name)).toEqual(['a.dwg', 'b.dxf', 'c.pdf'])
    expect(await screen.findByRole('status')).toHaveTextContent('Uploaded 3 files')
  })

  it('lists the files that failed by name without hiding the ones that worked', async () => {
    mutateAsync.mockResolvedValue([
      { filename: 'good.dxf', ok: true },
      { filename: 'bad.dwg', ok: false, error: 'bad.dwg is not a valid DWG file' },
    ])
    renderUpload()
    fireEvent.change(screen.getByTestId('drawing-file-input'), { target: { files: [file('good.dxf'), file('bad.dwg')] } })
    expect(await screen.findByRole('alert')).toHaveTextContent('bad.dwg: bad.dwg is not a valid DWG file')
    expect(screen.getByRole('status')).toHaveTextContent('Uploaded good.dxf')
  })
})
