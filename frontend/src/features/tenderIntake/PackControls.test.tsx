import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packageProgress } from './testFixtures'
import { ApiError } from '../../lib/api'
import { CostConfirmationRequiredError, type CostEstimate } from './types'

const m = vi.hoisted(() => ({
  pause: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
  confirm: vi.fn(),
  estimate: { data: undefined as unknown, error: null as unknown },
  estimateIds: [] as string[],
}))
vi.mock('./api', () => ({
  useCostEstimate: (id: string) => {
    m.estimateIds.push(id)
    return m.estimate
  },
  useConfirmCost: () => ({ mutate: m.confirm, isPending: false }),
  usePauseTenderPackage: () => ({ mutate: m.pause, isPending: false }),
  useResumeTenderPackage: () => ({ mutate: m.resume, isPending: false }),
  useCancelTenderPackage: () => ({ mutate: m.cancel, isPending: false }),
}))

import { PackControls } from './PackControls'

function est(over: Partial<CostEstimate> = {}): CostEstimate {
  return {
    package_id: 'pk1',
    provider: 'qwen',
    external: true,
    ai_available: true,
    files_needing_ai: 5,
    models: [{ model: 'qwen3.7-flash', tier: 'classify', calls: 5, avg_tokens_in: 2500, avg_tokens_cached: 0, avg_tokens_out: 250, est_usd: 1.5, rate_verified: true, basis: 'default' }],
    total_usd: 1.5,
    any_unverified: false,
    monthly_remaining_usd: null,
    project_remaining_usd: null,
    within_budget: true,
    confirmation_required: true,
    confirmed_at: null,
    confirmed_usd: null,
    note: '',
    ...over,
  }
}

describe('PackControls', () => {
  beforeEach(() => {
    for (const f of [m.pause, m.resume, m.cancel, m.confirm]) f.mockReset()
    m.estimate = { data: undefined, error: null }
    m.estimateIds = []
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

  it('Resume for a paused pack that needs no cost confirmation resumes without a modal', () => {
    m.estimate = { data: est({ external: false, confirmation_required: false }), error: null }
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    expect(screen.getByText(/Paused/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Pause/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    expect(m.estimateIds).toContain('pk1')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(m.resume.mock.calls[0][0]).toBe('pk1')
  })

  it('Resume -> estimate -> modal -> confirm -> resume', () => {
    m.estimate = { data: est(), error: null }
    m.confirm.mockImplementation((_v, opts) => opts.onSuccess())
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    const dialog = screen.getByRole('dialog', { name: 'Estimated AI cost' })
    expect(m.resume).not.toHaveBeenCalled()
    expect(dialog).toHaveTextContent('$1.50')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm and start' }))
    expect(m.confirm.mock.calls[0][0]).toEqual({ packageId: 'pk1', accepted_usd: 1.5 })
    expect(m.resume.mock.calls[0][0]).toBe('pk1')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('cancelling the cost modal resumes nothing', () => {
    m.estimate = { data: est(), error: null }
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(m.resume).not.toHaveBeenCalled()
    expect(m.confirm).not.toHaveBeenCalled()
  })

  it('a resume that answers the cost 409 opens the modal with the estimate from the error', () => {
    m.estimate = { data: est({ external: false, confirmation_required: false }), error: null }
    m.resume.mockImplementation((_id, opts) =>
      opts.onError(new CostConfirmationRequiredError(new ApiError(409, { type: 'urn:installtec:cost-confirmation-required', title: 'x', status: 409, estimate: est({ total_usd: 7 }) }))),
    )
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    expect(screen.getByRole('dialog', { name: 'Estimated AI cost' })).toHaveTextContent('$7.00')
  })

  it('shows an error when the estimate cannot be loaded', () => {
    m.estimate = { data: undefined, error: new Error('boom') }
    render(<PackControls projectId="p1" packages={[packageProgress({ status: 'paused' })]} canConfirm />)
    fireEvent.click(screen.getByRole('button', { name: 'Resume Transmittal 1' }))
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    expect(m.resume).not.toHaveBeenCalled()
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
