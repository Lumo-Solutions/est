import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api'
import { CostEstimateModal } from './CostEstimateModal'
import { CostConfirmationRequiredError, type CostEstimate } from './types'

const m = vi.hoisted(() => ({ mutate: vi.fn() }))
vi.mock('./api', () => ({
  useConfirmCost: () => ({ mutate: m.mutate, isPending: false }),
}))

function estimate(over: Partial<CostEstimate> = {}): CostEstimate {
  return {
    package_id: 'pk1',
    provider: 'qwen',
    external: true,
    ai_available: true,
    files_needing_ai: 42,
    models: [
      { model: 'qwen3.7-flash', tier: 'classify', calls: 40, avg_tokens_in: 2500, avg_tokens_cached: 100, avg_tokens_out: 250, est_usd: 0.31, rate_verified: true, basis: 'history' },
      { model: 'qwen3.7-plus', tier: 'vision', calls: 2, avg_tokens_in: 6000, avg_tokens_cached: 0, avg_tokens_out: 300, est_usd: 1.234, rate_verified: false, basis: 'default' },
    ],
    total_usd: 1.544,
    any_unverified: true,
    monthly_remaining_usd: 88.5,
    project_remaining_usd: null,
    within_budget: true,
    confirmation_required: true,
    confirmed_at: null,
    confirmed_usd: null,
    note: 'Reading starts after you confirm.',
    ...over,
  }
}

function renderModal(est: CostEstimate, extra: { onClose?: () => void; onConfirmed?: () => void } = {}) {
  const onClose = extra.onClose ?? vi.fn()
  const onConfirmed = extra.onConfirmed ?? vi.fn()
  render(<CostEstimateModal open packageId="pk1" projectId="p1" estimate={est} onClose={onClose} onConfirmed={onConfirmed} />)
  return { onClose, onConfirmed }
}

describe('CostEstimateModal', () => {
  beforeEach(() => {
    m.mutate.mockReset()
  })

  it('formats a tiny total as "< $0.01"', () => {
    renderModal(estimate({ total_usd: 0.004, models: [], any_unverified: false }))
    expect(screen.getByText(/Total:/)).toHaveTextContent('Total: < $0.01')
  })

  it('shows the total, file count, per-model rows, budget and note', () => {
    renderModal(estimate())
    const dialog = screen.getByRole('dialog', { name: 'Estimated AI cost' })
    expect(dialog).toHaveTextContent('Total: $1.54')
    expect(dialog).toHaveTextContent('Files needing AI: 42')
    const rows = within(dialog).getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveTextContent('classify')
    expect(rows[1]).toHaveTextContent('qwen3.7-flash')
    expect(rows[1]).toHaveTextContent('2500')
    expect(rows[1]).toHaveTextContent('$0.31')
    expect(dialog).toHaveTextContent('Monthly budget remaining: $88.50')
    expect(dialog).not.toHaveTextContent('Project budget remaining')
    expect(dialog).toHaveTextContent('Reading starts after you confirm.')
  })

  it('marks unverified rows and the total, with the explanation, and leaves verified rows alone', () => {
    renderModal(estimate())
    const rows = screen.getAllByRole('row')
    expect(rows[1]).not.toHaveTextContent('unverified')
    expect(rows[2]).toHaveTextContent('unverified')
    expect(screen.getByText(/Total:/)).toHaveTextContent('unverified')
    expect(screen.getByText('Price not yet checked against your provider invoice.')).toBeInTheDocument()
  })

  it('no unverified wording when every rate is verified', () => {
    renderModal(estimate({ any_unverified: false, models: estimate().models.map((x) => ({ ...x, rate_verified: true })) }))
    expect(screen.queryByText(/unverified/)).not.toBeInTheDocument()
    expect(screen.queryByText(/not yet checked/)).not.toBeInTheDocument()
  })

  it('warns when over budget', () => {
    renderModal(estimate({ within_budget: false }))
    expect(screen.getByRole('alert')).toHaveTextContent('over the remaining AI budget')
  })

  it('confirm sends the displayed total, then closes and reports', () => {
    m.mutate.mockImplementation((_v, opts) => opts.onSuccess())
    const { onClose, onConfirmed } = renderModal(estimate())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and start' }))
    expect(m.mutate.mock.calls[0][0]).toEqual({ packageId: 'pk1', accepted_usd: 1.544 })
    expect(onClose).toHaveBeenCalled()
    expect(onConfirmed).toHaveBeenCalled()
  })

  it('Cancel confirms nothing', () => {
    const { onClose } = renderModal(estimate())
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(m.mutate).not.toHaveBeenCalled()
  })

  it('when the estimate grew, shows the new numbers and says it changed without closing', async () => {
    const grown = estimate({ total_usd: 2.5, files_needing_ai: 60 })
    m.mutate.mockImplementation((_v, opts) =>
      opts.onError(new CostConfirmationRequiredError(new ApiError(409, { type: 'urn:installtec:cost-confirmation-required', title: 'x', status: 409, estimate: grown }))),
    )
    const { onClose, onConfirmed } = renderModal(estimate())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and start' }))
    await waitFor(() => expect(screen.getByText(/Total:/)).toHaveTextContent('$2.50'))
    expect(screen.getByRole('status')).toHaveTextContent('The estimate changed')
    expect(screen.getByText(/Files needing AI:/)).toHaveTextContent('60')
    expect(onClose).not.toHaveBeenCalled()
    expect(onConfirmed).not.toHaveBeenCalled()
    // The next confirm sends the new total.
    m.mutate.mockReset()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and start' }))
    expect(m.mutate.mock.calls[0][0].accepted_usd).toBe(2.5)
  })

  it('shows other errors', () => {
    m.mutate.mockImplementation((_v, opts) => opts.onError(new Error('Server down')))
    renderModal(estimate())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and start' }))
    expect(screen.getByText('Server down')).toBeInTheDocument()
  })

  it('a non-external provider has no per-call cost and a plain Start button', () => {
    renderModal(estimate({ external: false, provider: 'local', models: [], total_usd: 0, any_unverified: false }))
    expect(screen.getByText(/No per-call cost/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm and start' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
  })
})
