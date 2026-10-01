import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IntakeProgress } from './IntakeProgress'
import { packageProgress, treeSummary } from './testFixtures'

describe('IntakeProgress', () => {
  it('renders nothing when nothing is happening', () => {
    const { container } = render(<IntakeProgress summary={treeSummary({ total: 5 })} packages={[packageProgress({ status: 'ready' })]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows Uploaded U of E files while bytes are still arriving', () => {
    render(
      <IntakeProgress
        summary={treeSummary({ total: 40, pending_upload: 60 })}
        packages={[packageProgress({ status: 'uploading', expected_count: 100, registered: 100, uploaded: 40, pending_upload: 60 })]}
      />,
    )
    expect(screen.getByText('Uploaded 40 of 100 files')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Files uploaded' })).toHaveAttribute('aria-valuenow', '40')
    expect(screen.queryByText(/This upload was not finished/)).not.toBeInTheDocument()
  })

  it('explains an upload that stopped half way and how to continue', () => {
    render(
      <IntakeProgress
        summary={treeSummary({ total: 30 })}
        packages={[packageProgress({ status: 'uploading', expected_count: 100, registered: 30, uploaded: 30, pending_upload: 0 })]}
      />,
    )
    expect(screen.getByText(/This upload was not finished \(30 of 100 files arrived\)\. Drop the same folder again under .Add more files. to continue\./)).toBeInTheDocument()
  })

  it('shows Reading documents D of T with the per-state counts, from the summary only', () => {
    render(<IntakeProgress summary={treeSummary({ total: 10, in_progress: 4, by_display_status: { reading: 3, queued: 1, ready: 6 } })} />)
    expect(screen.getByText('Reading documents: 6 of 10')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Documents read' })
    expect(bar).toHaveAttribute('aria-valuenow', '6')
    expect(bar).toHaveAttribute('aria-valuemax', '10')
    expect(screen.getByText(/Reading:/)).toBeInTheDocument()
    expect(screen.getByText(/Queued:/)).toBeInTheDocument()
  })

  it('says unpacking while a pack is processing and no file has arrived yet', () => {
    render(<IntakeProgress summary={treeSummary({ packages_processing: 1 })} />)
    expect(screen.getByText('Unpacking your upload...')).toBeInTheDocument()
  })

  it('shows a paused banner', () => {
    render(<IntakeProgress summary={treeSummary({ total: 10 })} packages={[packageProgress({ status: 'paused' })]} />)
    expect(screen.getByText(/This pack is paused/)).toBeInTheDocument()
  })
})
