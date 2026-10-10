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
const usage = {
  month_to_date_usd: 12.5,
  monthly_budget_usd: 100,
  project_budget_usd: null,
  rows: [
    { task: 'boq_match', provider: 'openai', model: 'gpt-x', calls: 7, cached: 2, errors: 1, blocked: 0, tokens_in: 1000, tokens_cached: 321, tokens_out: 500, cost_usd: 1.23, rate_verified: true },
    { task: 'intake_classify', provider: 'qwen', model: 'qwen3.7-plus', calls: 3, cached: 0, errors: 0, blocked: 0, tokens_in: 90, tokens_cached: 0, tokens_out: 40, cost_usd: 0.42, rate_verified: false },
  ],
  recent: [
    { id: 'c1', created_at: '2026-09-01T10:00:00Z', task: 'boq_match', provider: 'openai', model: 'gpt-x', project_id: null, entity_type: null, entity_id: null, status: 'ok', tokens_in: 10, tokens_out: 5, cost_usd: 0.01, latency_ms: 420, error: null, created_by: null },
  ],
} as unknown as AiUsageOut

let aiClassify: boolean | undefined = false

function setup(status: AiStatusOut = okStatus) {
  get.mockImplementation((path: string) => {
    if (path.startsWith('/tender-intake/settings'))
      return Promise.resolve({ auto_accept_min: 0.85, default_auto_accept_min: 0.85, auto_measure_disciplines: ['stormwater'], ...(aiClassify === undefined ? {} : { ai_classify: aiClassify }) })
    return Promise.resolve(path.startsWith('/ai/status') ? status : usage)
  })
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
    aiClassify = false
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

  it('shows cached tokens and marks unverified rates', async () => {
    roles = [Role.BD_DIRECTOR]
    setup()
    expect(await screen.findByText(/\$0\.42/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Cached tokens' })).toBeInTheDocument()
    expect(screen.getByText('321')).toBeInTheDocument()
    const rows = screen.getAllByRole('row')
    const verified = rows.find((r) => r.textContent?.includes('$1.23'))!
    const unverified = rows.find((r) => r.textContent?.includes('$0.42'))!
    expect(unverified).toHaveTextContent('unverified')
    expect(verified).not.toHaveTextContent('unverified')
    expect(screen.getByText(/Price not yet checked against your provider invoice/)).toBeInTheDocument()
  })

  it('does not request usage for other roles', async () => {
    roles = [Role.ESTIMATOR]
    setup()
    await screen.findByRole('switch')
    expect(get.mock.calls.some((c) => String(c[0]).includes('/admin/ai-usage'))).toBe(false)
    expect(screen.getByText(/cannot view AI usage/)).toBeInTheDocument()
  })

  describe('intake auto-accept', () => {
    const label = 'Auto-accept at or above (%)'

    it('shows the current value', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      expect(await screen.findByText('85%')).toBeInTheDocument()
      expect(screen.getByLabelText(label)).toHaveValue(85)
    })

    it('lets the managing director save a new value', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      fireEvent.change(await screen.findByLabelText(label), { target: { value: '90' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/intake-settings', { auto_accept_min: 0.9 }))
      expect(await screen.findByText('Saved')).toBeInTheDocument()
    })

    it('converts percent to a two-decimal fraction', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      fireEvent.change(await screen.findByLabelText(label), { target: { value: '87' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/intake-settings', { auto_accept_min: 0.87 }))
    })

    it('blocks Save when out of range', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      const input = await screen.findByLabelText(label)
      fireEvent.change(input, { target: { value: '49' } })
      expect(screen.getByText(/from 50 to 100/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
      fireEvent.change(input, { target: { value: '101' } })
      expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
      expect(put).not.toHaveBeenCalled()
    })

    it('is read-only for other roles', async () => {
      roles = [Role.BD_DIRECTOR]
      setup()
      expect(await screen.findByLabelText(label)).toBeDisabled()
      expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
      expect(screen.getAllByText('Only the managing director can change this').length).toBeGreaterThan(0)
    })

    it('shows server errors', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      put.mockRejectedValue(new Error('Value rejected by server'))
      fireEvent.change(await screen.findByLabelText(label), { target: { value: '95' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Value rejected by server')
    })
  })

  describe('measure automatically on intake', () => {
    it('lists the disciplines with the saved ones ticked and explains the other ways drawings get measured', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      expect(await screen.findByRole('checkbox', { name: 'Stormwater drainage' })).toBeChecked()
      expect(screen.getByRole('checkbox', { name: 'Roads / civil' })).not.toBeChecked()
      expect(screen.getByText(/when opened, when the verification report needs them, or by "Measure all"/)).toBeInTheDocument()
    })

    it('saves the ticked disciplines only', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      fireEvent.click(await screen.findByRole('checkbox', { name: 'Roads / civil' }))
      fireEvent.click(screen.getByRole('button', { name: 'Save automatic measuring' }))
      await waitFor(() =>
        expect(put).toHaveBeenCalledWith('/admin/intake-settings', { auto_measure_disciplines: ['stormwater', 'roads_civil'] }),
      )
    })

    it('can clear the list back to none', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      fireEvent.click(await screen.findByRole('checkbox', { name: 'Stormwater drainage' }))
      fireEvent.click(screen.getByRole('button', { name: 'Save automatic measuring' }))
      await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/intake-settings', { auto_measure_disciplines: [] }))
    })

    it('is read-only for other roles', async () => {
      roles = [Role.BD_DIRECTOR]
      setup()
      expect(await screen.findByRole('checkbox', { name: 'Roads / civil' })).toBeDisabled()
      expect(screen.queryByRole('button', { name: 'Save automatic measuring' })).not.toBeInTheDocument()
    })
  })

  describe('classify every uploaded file with the AI', () => {
    const name = 'Classify every uploaded file with the AI'

    it('is off by default and explains what off and on mean', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      aiClassify = undefined // an older server that does not send the field yet
      setup()
      const sw = await screen.findByRole('switch', { name })
      expect(sw).not.toBeChecked()
      expect(screen.getByText(/uploads are indexed in seconds and nothing is sent to a model/)).toBeInTheDocument()
      expect(screen.getByText(/the estimation agent reads only what it needs/)).toBeInTheDocument()
      expect(screen.getByText(/On: every file is classified by the AI, which is slow, costs money and needs the cost confirmation/)).toBeInTheDocument()
    })

    it('reflects the saved value', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      aiClassify = true
      setup()
      expect(await screen.findByRole('switch', { name })).toBeChecked()
    })

    it('saves ai_classify when the managing director flips it', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      setup()
      fireEvent.click(await screen.findByRole('switch', { name }))
      await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/intake-settings', { ai_classify: true }))
    })

    it('turns it back off', async () => {
      roles = [Role.MANAGING_DIRECTOR]
      aiClassify = true
      setup()
      fireEvent.click(await screen.findByRole('switch', { name }))
      await waitFor(() => expect(put).toHaveBeenCalledWith('/admin/intake-settings', { ai_classify: false }))
    })

    it('is read-only for other roles', async () => {
      roles = [Role.BD_DIRECTOR]
      setup()
      const sw = await screen.findByRole('switch', { name })
      expect(sw).toBeDisabled()
      fireEvent.click(sw)
      expect(put).not.toHaveBeenCalled()
    })
  })
})
