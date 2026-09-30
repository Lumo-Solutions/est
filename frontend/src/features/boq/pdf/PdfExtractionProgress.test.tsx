import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { makeExtraction } from './fixtures'
import { PdfExtractionProgress } from './PdfExtractionProgress'

describe('PdfExtractionProgress', () => {
  it('shows pages done of total while running', () => {
    render(
      <PdfExtractionProgress
        extraction={makeExtraction({ status: 'running', pages_done: 1, pages_total: 4, pages: [{ page: 1, status: 'table' }] })}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('1 of 4 pages read')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
    expect(screen.getByText('Table read')).toBeInTheDocument()
  })

  it('lists human labels per page and shows warnings when ready', () => {
    render(
      <PdfExtractionProgress
        extraction={makeExtraction({
          warnings: ['Page 3 looked like a scan'],
          pages: [
            { page: 1, status: 'table' },
            { page: 2, status: 'ai' },
            { page: 3, status: 'skipped_collection' },
            { page: 4, status: 'empty' },
            { page: 5, status: 'ai_unavailable' },
          ],
        })}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Page 3 looked like a scan')
    for (const label of ['Table read', 'AI-read, needs review', 'Collection page skipped', 'No rows', 'Not read (AI unavailable)']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows the error and a working Retry when failed', () => {
    const onRetry = vi.fn()
    render(<PdfExtractionProgress extraction={makeExtraction({ status: 'failed', error: 'corrupt file' })} onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('corrupt file')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalled()
  })
})
