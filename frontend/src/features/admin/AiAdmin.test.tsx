import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Role } from '../../lib/roles'
import type { AiStatusOut, AiUsageOut } from '../../types/api'
import { AiAdmin } from './AiAdmin'

const get = vi.fn()
const put = vi.fn()
vi.mock('../../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), put: (...a: unknown[]) => put(...a) },
}))

let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const okStatus: AiStatusOut = {
  provider: 'openai',
  external: true,
  configured: true,
  external_ai_allowed: false,
  available: false,
  message: 'External AI is not allowed for this organisation',
}
const usage: AiUsageOut = {
  month_to_date_usd: 12.5,
  monthly_budget_usd: 100,
  project_budget_usd: null,
  rows: [
    { task: 'boq_match', provider: 'openai', model: 'gpt-x', calls: 7, cached: 2, errors: 1, blocked: 0, tokens_in: 1000, tokens_out: 500, cost_usd: 1.23 },
  ],
  recent: [
    { id: 'c1', created_at: '2026-09-01T10:00:00Z', task: 'boq_match', provider: 'openai', model: 'gpt-x', project_id: null, entity_type: null, entity_id: null, status: 'ok', tokens_in: 10, tokens_out: 5, cost_usd: 0.01, latency_ms: 420, error: null, created_by: null },
  ],
}

function setup(status: AiStatusOut = okStatus) {
  get.mockImplementation((path: string) => Promise.resolve(path.startsWith('/ai/status') ? status : usage))
  put.mockResolvedValue({})
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AiAdmin />
    </QueryClientProvider>,
  )
}

describe('AiAdmin', () => {
  beforeEach(() => {
    get.mockReset()
    put.mockReset()
  })

  it('shows the not-configured notice', async () => {
    roles = [Role.ESTIMATOR]
    setup({ ...okStatus, configured: false, message: 'AI not configured' })
    expect(await screen.findByRole('status')).toHaveTextContent('AI not configured')
    expect(screen.getByText('Not configured')).toBeInTheDocument()
  })

  it('lets the managing director toggle via a confirm modal', async () => {
    roles = [Role.MANAGING_DIRECTOR]
    setup()
    const sw = await screen.findByRole('switch', { name: 'External AI allowed' })
    expect(sw).toBeEnabled()
    fireEvent.click(sw)
    expect(await screen.findByText(/Tenant documents will be sent/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/ai-settings', { external_ai_allowed: true }))
  })

  it('shows the switch read-only for non-managing-director roles', async () => {
    roles = [Role.BD_DIRECTOR]
    setup()
    const sw = await screen.findByRole('switch', { name: 'External AI allowed' })
    expect(sw).toBeDisabled()
    expect(screen.getByText(/Only the managing director/)).toBeInTheDocument()
  })

  it('renders usage rows for admin roles', async () => {
    roles = [Role.BD_DIRECTOR]
    setup()
    expect(await screen.findByText('$1.23')).toBeInTheDocument()
    expect(screen.getByText(/monthly budget/)).toBeInTheDocument()
    expect(screen.getByText('420 ms')).toBeInTheDocument()
  })

  it('does not request usage for other roles', async () => {
    roles = [Role.ESTIMATOR]
    setup()
    await screen.findByRole('switch')
    expect(get.mock.calls.some((c) => String(c[0]).includes('/admin/ai-usage'))).toBe(false)
    expect(screen.getByText(/cannot view AI usage/)).toBeInTheDocument()
  })
})
