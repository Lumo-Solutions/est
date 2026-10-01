import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packageProgress } from './testFixtures'

const m = vi.hoisted(() => ({ pause: vi.fn(), resume: vi.fn(), cancel: vi.fn() }))
vi.mock('./api', () => ({
  usePauseTenderPackage: () => ({ mutate: m.pause, isPending: false }),
  useResumeTenderPackage: () => ({ mutate: m.resume, isPending: false }),
  useCancelTenderPackage: () => ({ mutate: m.cancel, isPending: false }),
}))

import { PackControls } from './PackControls'

describe('PackControls', () => {
  beforeEach(() => {
    for (const f of [m.pause, m.resume, m.cancel]) f.mockReset()
  })

  it('shows nothing below lead estimator', () => {
    const { container } = render(<PackControls projectId="p1" packages={[packageProgress()]} canConfirm={false} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows nothing when no pack is uploading, processing or paused', () => {
    const { container } = render(
      <PackControls
        projectId="p1"
        packages={[packageProgress({ status: 'ready' }), packageProgress({ id: 'pk2', status: 'cancelled' }), packageProgress({ id: 'pk3', status: 'failed' })]}
        canConfirm
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('Pause and Cancel for a running pack, naming the pack, with its status', () => {
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'processing' })]} canConfirm />)
    expect(screen.getByText(/Processing/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Resume/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pause Transmittal 1' }))
    expect(m.pause.mock.calls[0][0]).toBe('pk1')
    expect(screen.getByRole('button', { name: 'Cancel Transmittal 1' })).toBeInTheDocument()
  })

  it('an uploading pack can be paused too', () => {
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'uploading' })]} canConfirm />)
    expect(screen.getByText(/Uploading/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pause Transmittal 1' })).toBeInTheDocument()
  })

  it('Resume for a paused pack', () => {
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    expect(screen.getByText(/Paused/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Pause/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    expect(m.resume.mock.calls[0][0]).toBe('pk1')
  })

  it('Cancel needs the confirm modal and says what happens', () => {
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'processing' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel Transmittal 1' }))
    expect(m.cancel).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: 'Cancel Transmittal 1?' })
    expect(dialog).toHaveTextContent('Files not yet read are left out; files already sorted stay')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel pack' }))
    expect(m.cancel.mock.calls[0][0]).toBe('pk1')
  })

  it('backing out of the modal cancels nothing', () => {
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'processing' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel Transmittal 1' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(m.cancel).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the error text of a failed call', () => {
    m.pause.mockImplementation((_id, opts) => opts.onError(new Error('This pack cannot be paused')))
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'processing' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Pause Transmittal 1' }))
    expect(screen.getByRole('alert')).toHaveTextContent('This pack cannot be paused')
  })
})
