import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentLine, estimateLine, proposal } from '../features/agentLines/fixtures'
import type { AgentLine } from '../features/agentLines/types'
import { ApiError } from '../lib/api'
import { Role } from '../lib/roles'

const get = vi.fn()
vi.mock('../lib/api', async (orig) => ({
  ...(await orig<typeof import('../lib/api')>()),
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn() },
}))

let roles: string[] = []
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { sub: 'u-me' }, hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const SETTLEMENT = {
  id: 's1',
  project_id: 'p1',
  version_no: 1,
  is_current: true,
  status: 'draft',
  currency: 'AED',
  default_plant_pct: 5,
  default_overhead_pct: 5,
  default_volatility_pct: 2,
  default_markup_pct: 10,
  submitted_by: null,
  margin_on_sell_pct: null,
}
const L1 = 'l1aaaaaa-0000-0000-0000-000000000000'
const L2 = 'l2bbbbbb-0000-0000-0000-000000000000'
const L3 = 'l3cccccc-0000-0000-0000-000000000000'
const lineRow = (id: string, cost_source: string) => ({
  id,
  boq_line_item_id: `b-${id}`,
  quantity: 10,
  quantity_at_build: 10,
  direct_unit_cost: 100,
  source_currency: 'AED',
  cost_source,
  fx_rate: null,
  unit_sell_rate: 120,
  line_amount: 1200,
})
const DETAIL = {
  ...SETTLEMENT,
  trade_overrides: [],
  lines: [lineRow(L1, 'agent_candidate'), lineRow(L2, 'agent_estimate'), lineRow(L3, 'manual')],
}

const { submitMutate, idle } = vi.hoisted(() => ({
  submitMutate: vi.fn(),
  idle: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
}))
vi.mock('../features/settlement/api', () => ({
  useBuildSettlementDraft: idle,
  useDecideSettlement: idle,
  useDeleteScenario: idle,
  useRefreshQuantities: idle,
  useSaveScenario: idle,
  useScenarios: () => ({ data: [] }),
  useSettlement: () => ({ data: DETAIL }),
  useSetLineFxRate: idle,
  useSetTradeOverride: idle,
  useSimulate: idle,
  useSubmitSettlement: () => ({ mutate: submitMutate, isPending: false, isError: false, error: null }),
  useUpdateSettlementLine: idle,
}))
vi.mock('../features/settlement/useCurrentSettlement', () => ({
  useCurrentSettlement: () => ({ current: SETTLEMENT, isLoading: false, isError: false, error: null }),
}))
vi.mock('../features/admin/api', () => ({ useTaxonomyNodes: () => ({ data: [] }) }))
vi.mock('../features/tenderIntake/api', () => ({ useProjectAddenda: () => ({ data: [] }) }))
vi.mock('../features/settlementAi/AiCostProposalsPanel', () => ({ AiCostProposalsPanel: () => null }))
vi.mock('../features/settlementAi/MarkupAdvicePanel', () => ({ MarkupAdvicePanel: () => null }))

import { SettlementPage } from './SettlementPage'

let agentLines: AgentLine[] = []
let unconfirmed = 0

function setup(role: string) {
  roles = [role]
  get.mockImplementation((path: string) => {
    if (path.endsWith('/agent-summary')) return Promise.resolve({ agent_lines: agentLines.length, unconfirmed })
    if (path.endsWith('/agent-lines')) return Promise.resolve(agentLines)
    return Promise.reject(new Error(`unexpected ${path}`))
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/settlement']}>
        <Routes>
          <Route path="/projects/:projectId/settlement" element={<SettlementPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const rowOf = (id: string) => within(document.getElementById(`agent-line-${id}`) as HTMLElement)

describe('SettlementPage agent lines', () => {
  beforeEach(() => {
    get.mockReset()
    submitMutate.mockReset()
    agentLines = [
      agentLine({ line_id: L1 }),
      estimateLine({ line_id: L2 }),
    ]
    unconfirmed = 2
  })

  it('shows the banner with the count, the source badges, confidence and flag chips', async () => {
    setup(Role.LEAD_ESTIMATOR)
    expect(await screen.findByText('2 agent lines need confirmation before submit')).toBeInTheDocument()
    expect(rowOf(L1).getByText('Agent: source')).toBeInTheDocument()
    expect(rowOf(L1).getByText('92%')).toBeInTheDocument()
    expect(rowOf(L1).getByText('Stale rate')).toBeInTheDocument()
    expect(rowOf(L2).getByText('Agent: estimate')).toBeInTheDocument()
    expect(rowOf(L2).getByText('No document check')).toBeInTheDocument()
    expect(rowOf(L3).queryByText(/Agent:/)).not.toBeInTheDocument()
  })

  it('shows Confirmed on a confirmed line and drops the banner when nothing is left', async () => {
    agentLines = [agentLine({ line_id: L1, agent_confirmed_by: 'u1', agent_confirmed_at: '2026-10-02T08:00:00Z' })]
    unconfirmed = 0
    setup(Role.LEAD_ESTIMATOR)
    expect(await rowOf(L1).findByText('Confirmed')).toBeInTheDocument()
    expect(screen.queryByText(/need confirmation before submit/)).not.toBeInTheDocument()
    expect(screen.queryByText(/needs confirmation before submit/)).not.toBeInTheDocument()
  })

  it('Review filters the lines to the unconfirmed agent lines', async () => {
    agentLines = [agentLine({ line_id: L1, agent_confirmed_by: 'u1' }), estimateLine({ line_id: L2 })]
    unconfirmed = 1
    setup(Role.LEAD_ESTIMATOR)
    await screen.findByText('1 agent line needs confirmation before submit')
    expect(document.getElementById(`agent-line-${L3}`)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(document.getElementById(`agent-line-${L3}`)).not.toBeInTheDocument()
    expect(document.getElementById(`agent-line-${L1}`)).not.toBeInTheDocument()
    expect(document.getElementById(`agent-line-${L2}`)).toBeInTheDocument()
    expect(document.activeElement).toBe(document.getElementById(`agent-line-${L2}`))
    fireEvent.click(screen.getByRole('button', { name: 'Show all lines' }))
    expect(document.getElementById(`agent-line-${L3}`)).toBeInTheDocument()
  })

  it('shows the banner reason next to Submit and focuses the first unconfirmed line on a 409', async () => {
    submitMutate.mockImplementation((_v: unknown, opts: { onError?: (e: unknown) => void }) =>
      opts.onError?.(
        new ApiError(409, { type: 'about:blank', title: 'Conflict', status: 409, unconfirmed_agent_line_ids: [L2, L1] }),
      ),
    )
    setup(Role.MANAGING_DIRECTOR)
    const submit = await screen.findByRole('button', { name: 'Submit for approval' })
    await waitFor(() => expect(submit.parentElement).toHaveTextContent('2 agent lines need confirmation before submit'))
    fireEvent.click(submit)
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById(`agent-line-${L2}`)))
    expect(document.getElementById(`agent-line-${L3}`)).not.toBeInTheDocument()
  })

  it('opens the evidence drawer from the badge; Replace opens the existing cost entry for that line', async () => {
    agentLines = [agentLine({ line_id: L1, proposal: proposal({ rate: 135 }) })]
    unconfirmed = 1
    setup(Role.LEAD_ESTIMATOR)
    fireEvent.click(await rowOf(L1).findByRole('button', { name: /Agent: source/ }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('AED 135')
    expect(screen.queryByLabelText('Manual unit cost')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Replace' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const input = await screen.findByLabelText('Manual unit cost')
    expect(rowOf(L1).getByLabelText('Manual unit cost')).toBe(input)
    await waitFor(() => expect(document.activeElement).toBe(input))
  })

  it('estimators see badges and the drawer but no Bulk confirm, Confirm or Replace', async () => {
    setup(Role.ESTIMATOR)
    await screen.findByText('2 agent lines need confirmation before submit')
    expect(screen.queryByRole('button', { name: 'Bulk confirm' })).not.toBeInTheDocument()
    fireEvent.click(await rowOf(L1).findByRole('button', { name: /Agent: source/ }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Gulf Concrete quote Q-17')
    expect(within(dialog).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Replace' })).not.toBeInTheDocument()
    expect(within(dialog).getAllByRole('button', { name: 'Close' }).length).toBeGreaterThan(0)
  })
})
