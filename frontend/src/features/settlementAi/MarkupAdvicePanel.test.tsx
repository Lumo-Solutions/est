import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Role } from '../../lib/roles'
import type { MarkupAdviceResult, SettlementAiRun } from '../../types/api'
import { costsRun } from './fixtures'
import { MarkupAdvicePanel } from './MarkupAdvicePanel'

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
vi.mock('../../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a) },
}))
let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const result: MarkupAdviceResult = {
  options: [
    { label: 'competitive', markup_pct: 6, overhead_pct: 8, volatility_pct: 2, rationale: 'Sharper price.', tender_total: '1000000.00', margin_on_sell_pct: '5.500', required_role: 'bd_director', unresolved_lines: 0 },
    { label: 'balanced', markup_pct: 9, overhead_pct: 8, volatility_pct: 3, rationale: 'Middle road.', tender_total: '1100000.00', margin_on_sell_pct: '8.250', required_role: 'managing_director', unresolved_lines: 0 },
    { label: 'protective', markup_pct: 12, overhead_pct: 9, volatility_pct: 4, rationale: 'Cover risk.', tender_total: '1200000.00', margin_on_sell_pct: null, required_role: null, unresolved_lines: 2 },
  ],
  per_trade: [{ trade: 'Plumbing', markup_low: 7, markup_high: 10, volatility_low: 2, volatility_high: 4, rationale: 'Volatile copper.' }],
  overall: 'Overall note here.',
  history: [{ margin_bucket: '5-8%', bids: 10, won: 4, win_rate_pct: 40, avg_price_gap_when_lost_pct: 3.2 }],
  current: { tender_total: '1050000.00', margin_on_sell_pct: '7.000', required_role: 'bd_director' },
}
const markupRun = (over: Partial<SettlementAiRun> = {}): SettlementAiRun =>
  costsRun({ id: 'm1', kind: 'markup', counts: null, result, ...over })

function setup(role: string, run: SettlementAiRun = markupRun()) {
  roles = [role]
  get.mockImplementation((path: string) => {
    if (path.startsWith('/ai/status')) return Promise.resolve({ available: true, message: null })
    if (path.endsWith('/ai/runs')) return Promise.resolve([run])
    if (path.startsWith('/settlement-ai-runs/')) return Promise.resolve(run)
    return Promise.reject(new Error(`unexpected ${path}`))
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MarkupAdvicePanel projectId="pr1" settlementId="s1" currency="AED" />
    </QueryClientProvider>,
  )
}

describe('MarkupAdvicePanel', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    patch.mockReset()
    post.mockResolvedValue(markupRun())
    patch.mockResolvedValue({})
  })

  it('shows Suggest markup to lead estimator and above and starts a run', async () => {
    setup(Role.LEAD_ESTIMATOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Suggest markup' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/bid-settlements/s1/ai/markup-advice', { use_ai: true }))
  })

  it('hides Suggest markup and Use these values from an estimator', async () => {
    setup(Role.ESTIMATOR)
    expect(await screen.findByText('Balanced')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suggest markup' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Use these values/ })).not.toBeInTheDocument()
  })

  it('renders options with platform-computed figures, tables, note and usage', async () => {
    setup(Role.LEAD_ESTIMATOR)
    const balanced = await screen.findByRole('region', { name: 'Balanced option' })
    expect(balanced).toHaveTextContent('Markup: 9%')
    expect(balanced).toHaveTextContent('AED 1,100,000.00')
    expect(balanced).toHaveTextContent('Margin on sell: 8.250%')
    expect(balanced).toHaveTextContent('managing_director')
    expect(balanced).toHaveTextContent('Middle road.')
    expect(screen.getByRole('region', { name: 'Protective option' })).toHaveTextContent('2 unresolved')
    expect(screen.getByText('Plumbing')).toBeInTheDocument()
    expect(screen.getByText('5-8%')).toBeInTheDocument()
    expect(screen.getByText('Overall note here.')).toBeInTheDocument()
    expect(screen.getByText('Suggestions are advice only. You set the values.')).toBeInTheDocument()
    expect(screen.getByText('AI usage: 4 AI calls, $0.12')).toBeInTheDocument()
  })

  it('applies via the existing defaults call only after confirmation', async () => {
    setup(Role.BD_DIRECTOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Use these values: Balanced' }))
    expect(patch).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Use these values' }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/bid-settlements/s1/defaults', {
        default_markup_pct: 9,
        default_overhead_pct: 8,
        default_volatility_pct: 3,
      }),
    )
  })

  it('does not apply when the confirmation is cancelled', async () => {
    setup(Role.BD_DIRECTOR)
    fireEvent.click(await screen.findByRole('button', { name: 'Use these values: Competitive' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
  })
})
