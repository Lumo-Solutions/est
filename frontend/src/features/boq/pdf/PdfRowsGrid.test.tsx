import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { BoqPdfRow, BoqPdfRowIn } from '../../../types/api'
import { makeExtraction, makeRow } from './fixtures'
import { PdfRowsGrid } from './PdfRowsGrid'

vi.mock('./api', () => ({ openBoqPdfSource: vi.fn(() => Promise.resolve()) }))

const rows = [
  makeRow(),
  makeRow({ row_id: 'r2', item_no: '1.2', description: 'Conduit', ai_read: true, source: 'ai', confidence: 0.82, edited: true }),
  makeRow({ row_id: 'r3', item_no: '', description: 'Bad row', quantity: null, errors: ['Item number is required'] }),
]

function setup(extraRows: BoqPdfRow[] = rows) {
  const ex = makeExtraction({ rows: extraRows, error_count: extraRows.filter((r) => r.errors.length).length })
  const onSave = vi.fn((_rows: BoqPdfRowIn[]) => Promise.resolve({ ...ex, rows: extraRows, error_count: 0 }))
  const onImport = vi.fn()
  render(<PdfRowsGrid extraction={ex} onSave={onSave} onImport={onImport} />)
  return { onSave, onImport }
}

describe('PdfRowsGrid', () => {
  it('summarises rows and shows AI badge, edited marker and row errors', () => {
    setup()
    expect(screen.getByTestId('pdf-summary')).toHaveTextContent('3 rows, 1 with errors, 1 AI-read')
    expect(screen.getByText('AI-read 82%')).toBeInTheDocument()
    expect(screen.getByText('Edited')).toBeInTheDocument()
    expect(screen.getByText('Item number is required')).toBeInTheDocument()
    expect(screen.getByText(/original-workbook export is not available/)).toBeInTheDocument()
  })

  it('disables Import while rows have errors', () => {
    setup()
    expect(screen.getByRole('button', { name: 'Import 3 items' })).toBeDisabled()
  })

  it('filters to error rows and AI rows', () => {
    setup()
    fireEvent.click(screen.getByLabelText('Only rows with errors'))
    expect(screen.getAllByTestId('pdf-row')).toHaveLength(1)
    fireEvent.click(screen.getByLabelText('Only rows with errors'))
    fireEvent.click(screen.getByLabelText('Only AI-read'))
    expect(screen.getAllByTestId('pdf-row')).toHaveLength(1)
    expect(screen.getByDisplayValue('Conduit')).toBeInTheDocument()
  })

  it('enables Import when clean, disables it on edit, and saves the full list', async () => {
    const { onSave, onImport } = setup([makeRow(), makeRow({ row_id: 'r2', item_no: '1.2' })])
    const importBtn = screen.getByRole('button', { name: 'Import 2 items' })
    expect(importBtn).toBeEnabled()
    fireEvent.click(importBtn)
    expect(onImport).toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Quantity, row 1'), { target: { value: '12.5' } })
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import 2 items' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave.mock.calls[0][0]).toEqual([
      { row_id: 'r1', item_no: '1.1', description: 'Cable tray', uom: 'm', quantity: 12.5, page: 2 },
      { row_id: 'r2', item_no: '1.2', description: 'Cable tray', uom: 'm', quantity: 10, page: 2 },
    ])
    await waitFor(() => expect(screen.queryByText(/Unsaved changes/)).not.toBeInTheDocument())
  })

  it('adds a manual row without row_id and removes rows', async () => {
    const { onSave } = setup([makeRow()])
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText('Item no, row 2'), { target: { value: '9' } })
    fireEvent.change(screen.getByLabelText('Description, row 2'), { target: { value: 'Extra' } })
    fireEvent.click(screen.getByRole('button', { name: 'Remove row 1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave.mock.calls[0][0]).toEqual([{ item_no: '9', description: 'Extra', uom: '', quantity: null, page: 2 }])
  })
})
