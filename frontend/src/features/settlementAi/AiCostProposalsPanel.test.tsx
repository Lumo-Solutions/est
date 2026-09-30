import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Role } from '../../lib/roles'
import { AiCostProposalsPanel } from './AiCostProposalsPanel'
import { costsRun, proposal } from './fixtures'

const get = vi.fn()
const post = vi.fn()
vi.mock('../../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}))
let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

let items = [proposal()]
function setup(role: string) {
  roles = [role]
  get.mockImplementation((path: string) => {
    if (path.startsWith('/ai/status')) return Promise.resolve({ available: true, message: null })
    if (path.endsWith('/ai/runs')) return Promise.resolve([costsRun()])
    if (path.startsWith('/settlement-ai-runs/')) return Promise.resolve(costsRun())
    if (path.includes('/ai/proposals')) return Promise.resolve({ items, total: items.length, limit: 50, offset: 0 })
    return Promise.reject(new Error(`unexpected ${path}`))
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AiCostProposalsPanel projectId="pr1" settlementId="s1" currency="AED" />
    </QueryClientProvider>,
  )
}

describe('AiCostProposalsPanel', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    post.mockResolvedValue({})
    items = [proposal()]
  })

  it('shows run and bulk-accept buttons to a lead estimator', async () => {
    setup(Role.LEAD_ESTIMATOR)
    expect(await screen.findByRole('button', { name: 'Propose costs with AI' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept all high-confidence' })).toBeInTheDocument()
  })

  it('hides run and bulk-accept from an estimator but still lets them decide', async () => {
    setup(Role.ESTIMATOR)
    expect(await screen.findByText('PVC pipe 110mm')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Propose costs with AI' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept all high-confidence' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
  })

  it('starts a run with use_ai from the checkbox', async () => {
    setup(Role.LEAD_ESTIMATOR)
    fireEvent.click(await screen.findByLabelText('Use AI'))
    fireEvent.click(screen.getByRole('button', { name: 'Propose costs with AI' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/bid-settlements/s1/ai/cost-proposals', { use_ai: false }))
  })

  it('renders the summary, usage, source, confidence and labelled flags', async () => {
    setup(Role.LEAD_ESTIMATOR)
    expect(await screen.findByText('3 lines: 2 with a source, 1 need manual entry, 1 flagged')).toBeInTheDocument()
    expect(screen.getByText('AI usage: 4 AI calls, $0.12')).toBeInTheDocument()
    expect(screen.getByText('AI-matched')).toBeInTheDocument()
    expect(screen.getByText('Acme quote Q-7')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '92')
    expect(screen.getByText('Single source')).toBeInTheDocument()
    expect(screen.getByText('Unit differs')).toBeInTheDocument()
    expect(screen.getByText('Matches the size and material.')).toBeInTheDocument()
  })

  it('posts accept, choose and reject decisions', async () => {
    setup(Role.ESTIMATOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settlement-ai-proposals/p1/decision', { action: 'accept' }))
    fireEvent.click(screen.getByRole('button', { name: /other source/ }))
    expect(screen.getByText('Stale rate')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Use this instead/ }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/settlement-ai-proposals/p1/decision', { action: 'choose', candidate_ref: 'library:2' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settlement-ai-proposals/p1/decision', { action: 'reject' }))
  })

  it('requires a note for a manual cost', async () => {
    setup(Role.ESTIMATOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Enter cost manually' }))
    fireEvent.change(screen.getByLabelText(/Manual unit cost/), { target: { value: '9.5' } })
    const submit = screen.getByRole('button', { name: 'Set manual cost' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Why (required)'), { target: { value: 'budget estimate' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/settlement-ai-proposals/p1/decision', {
        action: 'manual',
        manual_unit_cost: 9.5,
        manual_currency: 'AED',
        note: 'budget estimate',
      }),
    )
  })

  it('shows a no-source line plainly with the manual form open and no Accept', async () => {
    items = [proposal({ chosen: null, candidates: [], no_source: true, source: 'none', flags: [], blocked: false, confidence: 0 })]
    setup(Role.ESTIMATOR)
    expect(await screen.findByText('No cost source: manual entry required')).toBeInTheDocument()
    expect(screen.getByLabelText('Why (required)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('shows who/when/status for a decided line without actions', async () => {
    items = [proposal({ status: 'accepted', decided_by: 'u-1', decided_at: '2026-09-02T09:00:00Z', decision_note: 'ok' })]
    setup(Role.ESTIMATOR)
    expect(await screen.findByText(/Accepted by u-1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  })

  it('confirms bulk accept, states the threshold and shows the returned counts', async () => {
    post.mockResolvedValue({ accepted: 5, skipped: 2 })
    setup(Role.LEAD_ESTIMATOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Accept all high-confidence' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('85%')
    expect(dialog).toHaveTextContent('Flagged lines are skipped')
    expect(post).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept all' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/bid-settlements/s1/ai/proposals:bulk-accept', { min_confidence: 0.85 }))
    expect(await screen.findByText('Accepted 5 lines, skipped 2.')).toBeInTheDocument()
  })
})
