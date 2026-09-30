import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Role } from '../lib/roles'
import type { VerificationLineOut, VerificationRunOut } from '../types/api'
import { VerificationPage } from './VerificationPage'

const get = vi.fn()
const post = vi.fn()
vi.mock('../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}))

let roles: string[] = []
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const aiOk = { provider: 'openai', external: true, configured: true, external_ai_allowed: true, available: true, message: null }

function makeRun(over: Partial<VerificationRunOut> = {}): VerificationRunOut {
  return {
    id: 'r1',
    project_id: 'p1',
    status: 'ready',
    use_ai: true,
    phase: null,
    progress_done: 0,
    progress_total: 0,
    counts: { match: 3, variance: 2, missing_in_drawings: 1, not_verifiable: 4, missing_in_boq: 1 },
    summary: {
      verifiable: 6,
      by_trade: [
        { trade: 'Plumbing', lines: 5, match: 2, variance: 2, missing_in_drawings: 1, not_verifiable: 0, abs_variance_pct_sum: 33.3 },
      ],
      top_risks: [{ line_id: 'l1', class: 'variance', delta_pct: 25, note: 'Large gap' }],
    },
    warnings: [],
    error: null,
    ai_calls: 4,
    ai_cost_usd: 0.12,
    started_at: null,
    finished_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

function makeLine(over: Partial<VerificationLineOut> = {}): VerificationLineOut {
  return {
    id: 'l1',
    run_id: 'r1',
    boq_line_item_id: 'b1',
    item_no: '1.1',
    description: 'PVC pipe 110mm',
    trade_name: 'Plumbing',
    vclass: 'variance',
    method: 'measured',
    mapped_by: 'ai',
    boq_quantity: 100,
    boq_uom: 'm',
    drawing_quantity: 125,
    delta: 25,
    delta_pct: 25,
    confidence: 0.9,
    note: null,
    flags: [],
    interpretation: { work_type: 'pipe', material: 'PVC', size_mm: 110, unit: 'm', trade: 'Plumbing', source: 'ai', keywords: [] },
    evidence: [
      { ref: 'm:abc-123', kind: 'measurement', value: 125, unit: 'm', label: 'Run A', drawing_id: 'd1', sheet_id: 's1', page: 3, bbox: null, layer: null, confidence: 0.9, material: null },
    ],
    candidates: [{ ref: 'm:abc-123', score: 0.9, reason: 'Same size and material', source: 'ai', selected: true }],
    ...over,
  }
}

const missingInBoq = makeLine({
  id: 'l2',
  boq_line_item_id: null,
  item_no: null,
  description: 'Unaccounted duct',
  vclass: 'missing_in_boq',
  candidates: [],
})

let run = makeRun()
let lines: VerificationLineOut[] = []

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/verification']}>
        <Routes>
          <Route path="/projects/:projectId/verification" element={<VerificationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  roles = [Role.LEAD_ESTIMATOR]
  run = makeRun()
  lines = [makeLine(), missingInBoq]
  get.mockImplementation((path: string) => {
    if (path === '/ai/status') return Promise.resolve(aiOk)
    if (path === '/projects/p1/verification-runs') return Promise.resolve([run])
    if (path === '/verification-runs/r1') return Promise.resolve(run)
    if (path.startsWith('/verification-runs/r1/lines')) {
      const wanted = new URLSearchParams(path.split('?')[1]).get('vclass')
      const items = wanted ? lines.filter((l) => l.vclass === wanted) : lines
      return Promise.resolve({ items, total: items.length, limit: 200, offset: 0 })
    }
    if (path === '/projects/p1/drawing-annotations/summary')
      return Promise.resolve({ sheets: 10, done: 6, queued: 1, unavailable: 1, failed: 0, skipped: 0, unread: 2, annotations: 42 })
    if (path.startsWith('/projects/p1/verification-evidence')) return Promise.resolve({ items: [] })
    return Promise.reject(new Error(`unexpected GET ${path}`))
  })
})

describe('VerificationPage', () => {
  it('shows summary cards, verifiable count, trade table, AI usage and annotation summary', async () => {
    renderPage()
    expect(await screen.findByText('6 of 11 lines verifiable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Match/ })).toHaveTextContent('3')
    expect(screen.getByRole('table', { name: 'Variance by trade' })).toHaveTextContent('Plumbing')
    expect(screen.getByText('4 AI calls, $0.12')).toBeInTheDocument()
    expect(await screen.findByText(/42 annotations found/)).toBeInTheDocument()
    expect(screen.getByText(/never estimated/)).toBeInTheDocument()
  })

  it('filters the grid when a class card is clicked', async () => {
    renderPage()
    await screen.findByText('Unaccounted duct')
    fireEvent.click(screen.getByRole('button', { name: /^Variance/ }))
    await waitFor(() =>
      expect(get.mock.calls.some((c) => String(c[0]).includes('vclass=variance'))).toBe(true),
    )
    await waitFor(() => expect(screen.queryByText('Unaccounted duct')).not.toBeInTheDocument())
    expect(screen.getByText('PVC pipe 110mm')).toBeInTheDocument()
  })

  it('shows warnings prominently', async () => {
    run = makeRun({ warnings: ['3 sheets are not calibrated'] })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('3 sheets are not calibrated')
  })

  it('hides Start verification from estimators but still shows the report', async () => {
    roles = [Role.ESTIMATOR]
    renderPage()
    expect(await screen.findByText('6 of 11 lines verifiable')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start verification' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Read annotations with AI' })).not.toBeInTheDocument()
  })

  it('starts a run with the AI choice', async () => {
    post.mockResolvedValue(makeRun({ id: 'r2', status: 'queued' }))
    renderPage()
    await screen.findByText('6 of 11 lines verifiable')
    fireEvent.click(screen.getByLabelText('Use AI to map BOQ lines to drawing evidence'))
    fireEvent.click(screen.getByRole('button', { name: 'Start verification' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/projects/p1/verification-runs', { use_ai: false }))
  })

  it('shows progress while a run is running', async () => {
    run = makeRun({ status: 'running', phase: 'ranking', progress_done: 5, progress_total: 20 })
    renderPage()
    expect(await screen.findByText('Ranking drawing evidence')).toBeInTheDocument()
    expect(screen.getByText('5 of 20 (25%)')).toBeInTheDocument()
  })

  it('shows the error and a Retry button for a failed run', async () => {
    run = makeRun({ status: 'failed', error: 'worker crashed' })
    post.mockResolvedValue(makeRun({ id: 'r3', status: 'queued' }))
    renderPage()
    expect(await screen.findByText(/worker crashed/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/verification-runs/r1/retry'))
  })

  it('sends the right mapping request and updates the line in place', async () => {
    const updated = makeLine({ mapped_by: 'user', candidates: [{ ref: 'm:abc-123', score: 0.9, reason: 'x', source: 'ai', selected: true }] })
    post.mockResolvedValue({ line: updated, run: makeRun({ ai_calls: 9 }) })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Open line 1.1' }))
    const panel = await screen.findByRole('dialog', { name: /Line detail/ })
    expect(within(panel).getByRole('link', { name: 'Open on drawing' })).toHaveAttribute(
      'href',
      '/projects/p1/drawings/d1/sheets/2?measurement=abc-123',
    )
    expect(panel).toHaveTextContent(/links the measurement into the BOQ reconciliation/)
    fireEvent.click(within(panel).getByRole('button', { name: 'Accept m:abc-123' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/verification-runs/r1/lines/l1/mapping', {
        action: 'accept',
        evidence_ref: 'm:abc-123',
      }),
    )
    expect((await screen.findAllByText('Confirmed by estimator')).length).toBeGreaterThan(0)
    expect(await screen.findByText('9 AI calls, $0.12')).toBeInTheDocument()
  })

  it('shows the server message when a decision is rejected', async () => {
    post.mockRejectedValue(new Error('Units cannot be compared'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Open line 1.1' }))
    const panel = await screen.findByRole('dialog', { name: /Line detail/ })
    fireEvent.click(within(panel).getByRole('button', { name: 'Reject m:abc-123' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Units cannot be compared')
  })

  it('offers no accept/reject for a Missing in BOQ row', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Open line Unaccounted duct' }))
    const panel = await screen.findByRole('dialog', { name: /Line detail/ })
    expect(within(panel).queryByRole('button', { name: /Accept|Reject|Clear/ })).not.toBeInTheDocument()
    expect(panel).toHaveTextContent(/no BOQ line accounts for/)
  })
})
