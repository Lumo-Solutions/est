import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DropZone, type PathedFile } from './DropZone'

const f = (name: string) => new File(['x'], name, { type: 'application/pdf' })

describe('DropZone', () => {
  it('renders a named group, a labelled multi-file input and the help text', () => {
    render(<DropZone label="Tender files" onFiles={() => {}} />)
    const group = screen.getByRole('group', { name: 'Tender files' })
    expect(group).toHaveAttribute('aria-describedby')
    const input = screen.getByTestId('tender-file-input') as HTMLInputElement
    expect(input.multiple).toBe(true)
    expect(input.accept).toBe('.pdf,.dxf,.dwg,.xlsx,.xls,.csv,.docx,.doc,.jpg,.jpeg,.png,.zip')
    expect(screen.getByLabelText('Tender files', { selector: 'input' })).toBe(input)
    expect(screen.getByText(/up to 60 MB per file/)).toBeInTheDocument()
  })

  it('browse input change passes all files to onFiles', () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} />)
    const files = [f('a.pdf'), f('b.pdf'), f('c.pdf')]
    fireEvent.change(screen.getByTestId('tender-file-input'), { target: { files } })
    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles.mock.calls[0][0].map((x: File) => x.name)).toEqual(['a.pdf', 'b.pdf', 'c.pdf'])
  })

  it('a drop event calls onFiles', () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} />)
    fireEvent.drop(screen.getByRole('group', { name: 'Tender files' }), { dataTransfer: { files: [f('a.pdf'), f('b.pdf')] } })
    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles.mock.calls[0][0]).toHaveLength(2)
  })

  it('disabled ignores drops and disables the input', () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} disabled />)
    fireEvent.drop(screen.getByRole('group', { name: 'Tender files' }), { dataTransfer: { files: [f('a.pdf')] } })
    expect(onFiles).not.toHaveBeenCalled()
    expect(screen.getByTestId('tender-file-input')).toBeDisabled()
  })

  it('offers a labelled folder input and says folders are supported', () => {
    render(<DropZone label="Tender files" onFiles={() => {}} />)
    const folder = screen.getByTestId('tender-folder-input')
    expect(folder).toHaveAttribute('webkitdirectory')
    expect(screen.getByLabelText('Choose a folder')).toBe(folder)
    expect(screen.getByText(/Folders are supported/)).toBeInTheDocument()
  })

  it('folder input keeps webkitRelativePath as relativePath', () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} />)
    const a = f('C-101.pdf')
    Object.defineProperty(a, 'webkitRelativePath', { value: 'Tender Package/Drawings/C-101.pdf' })
    fireEvent.change(screen.getByTestId('tender-folder-input'), { target: { files: [a] } })
    expect((onFiles.mock.calls[0][0][0] as PathedFile).relativePath).toBe('Tender Package/Drawings/C-101.pdf')
  })

  it('walks dropped directories in batches and preserves relative paths', async () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} />)
    const fileEntry = (name: string, path: string) => ({
      isFile: true,
      isDirectory: false,
      name,
      fullPath: path,
      file: (ok: (file: File) => void) => ok(f(name)),
    })
    const dirEntry = (name: string, path: string, children: unknown[]) => {
      // Two batches, then empty: readEntries must be called until it returns [].
      const batches = [children.slice(0, 1), children.slice(1), []]
      return {
        isFile: false,
        isDirectory: true,
        name,
        fullPath: path,
        createReader: () => ({ readEntries: (ok: (e: unknown[]) => void) => ok(batches.shift() ?? []) }),
      }
    }
    const root = dirEntry('Tender Package', '/Tender Package', [
      dirEntry('Drawings', '/Tender Package/Drawings', [fileEntry('C-101.pdf', '/Tender Package/Drawings/C-101.pdf')]),
      fileEntry('spec.pdf', '/Tender Package/spec.pdf'),
    ])
    const items = [{ webkitGetAsEntry: () => root }]
    fireEvent.drop(screen.getByRole('group', { name: 'Tender files' }), { dataTransfer: { items, files: [] } })
    await waitFor(() => expect(onFiles).toHaveBeenCalledTimes(1))
    const paths = (onFiles.mock.calls[0][0] as PathedFile[]).map((x) => x.relativePath)
    expect(paths).toEqual(['Tender Package/Drawings/C-101.pdf', 'Tender Package/spec.pdf'])
  })

  it('silently skips junk and empty files and reports how many', () => {
    const onFiles = vi.fn()
    render(<DropZone label="Tender files" onFiles={onFiles} />)
    const files = [
      f('a.pdf'),
      f('.DS_Store'),
      f('Thumbs.db'),
      f('desktop.ini'),
      f('~$boq.xlsx'),
      f('._a.pdf'),
      new File([], 'empty.pdf', { type: 'application/pdf' }),
    ]
    fireEvent.change(screen.getByTestId('tender-file-input'), { target: { files } })
    expect(onFiles.mock.calls[0][0].map((x: File) => x.name)).toEqual(['a.pdf'])
    expect(screen.getByRole('status')).toHaveTextContent('Skipped 6 hidden, system or empty files.')
  })
})
