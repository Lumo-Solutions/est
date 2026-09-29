import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DropZone } from './DropZone'

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
})
