import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api'
import { AgentLineDrawer } from './AgentLineDrawer'
import { useAgentLines } from './api'
import { agentLine, estimateLine, proposal } from './fixtures'
import type { AgentLine } from './types'

const get = vi.fn()
const post = vi.fn()
vi.mock('../../lib/api', async (orig) => ({
  ...(await orig<typeof import('../../lib/api')>()),
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}))

let lines: AgentLine[] = []
const onClose = vi.fn()
const onReplace = vi.fn()

function Harness({ lineId, canAct = true, draft = true }: { lineId: string; canAct?: boolean; draft?: boolean }) {
  const { data } = useAgentLines('s1')
  const line = data?.find((l) => l.line_id === lineId) ?? null
  return <AgentLineDrawer line={line} settlementId="s1" canAct={canAct} draft={draft} onClose={onClose} onReplace={onReplace} />
}
function setup(lineId: string, props: { canAct?: boolean; draft?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Harness lineId={lineId} {...props} />
    </QueryClientProvider>,
  )
}

describe('AgentLineDrawer', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    onClose.mockReset()
    onReplace.mockReset()
    lines = [agentLine(), estimateLine()]
    get.mockImplementation(() => Promise.resolve(lines))
    post.mockResolvedValue({})
  })

  it('shows rate, currency, unit, as-of, source, evidence with page links, quantity check, flags, confidence and rationale', async () => {
    setup(lines[0].line_id)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('AED 120')
    expect(dialog).toHaveTextContent('per m3')
    expect(dialog).toHaveTextContent('2026-09-01')
    expect(dialog).toHaveTextContent('Gulf Concrete quote Q-17')
    expect(dialog).toHaveTextContent('quotation')
    const link = within(dialog).getByRole('link', { name: /Tender\/Quotes\/gulf.pdf, page 3/ })
    expect(link).toHaveAttribute('href', '/api/v1/tender-documents/f1/download#page=3')
    expect(link).toHaveAttribute('target', '_blank')
    expect(dialog).toHaveTextContent('Ready-mix C40 at AED 120 per m3')
    expect(dialog).toHaveTextContent('BOQ quantity 100, measured 108 m3 (+8%)')
    expect(dialog).toHaveTextContent('The BOQ quantity is never changed')
    expect(dialog).toHaveTextContent('older than the freshness limit')
    expect(dialog).toHaveTextContent('92%')
    expect(dialog).toHaveTextContent('The quote matches the spec clause.')
  })

  it('shows the method of an estimate', async () => {
    setup(lines[1].line_id)
    expect(await screen.findByText('Median of three similar lines, adjusted for volume')).toBeInTheDocument()
  })

  it('confirms with the id of the proposal it shows', async () => {
    setup(lines[0].line_id)
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/bid-settlements/s1/lines/l1aaaaaa-0000-0000-0000-000000000000/agent-confirm', { proposal_id: 'pr1' }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Confirmed')
  })

  it('on 409 reloads and shows the new proposal', async () => {
    post.mockRejectedValue(new ApiError(409, { type: 'about:blank', title: 'Conflict', status: 409 }))
    setup(lines[0].line_id)
    const confirm = await screen.findByRole('button', { name: 'Confirm' })
    // the line moved on: the next fetch returns a different proposal
    lines = [agentLine({ proposal: proposal({ id: 'pr9', rate: 135 }) }), estimateLine()]
    fireEvent.click(confirm)
    expect(await screen.findByRole('alert')).toHaveTextContent('look at the new proposal')
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('AED 135'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(post).toHaveBeenLastCalledWith(expect.any(String), { proposal_id: 'pr9' }))
  })

  it('keeps Confirm disabled for an estimate until the evidence is opened', async () => {
    setup(lines[1].line_id)
    const confirm = await screen.findByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    expect(screen.queryByRole('link', { name: /part3.pdf/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show evidence/ }))
    expect(screen.getByRole('link', { name: /part3.pdf, page 12/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(expect.stringContaining('/agent-confirm'), { proposal_id: 'pr2' }))
  })

  it('Replace hands the line to the existing cost entry', async () => {
    setup(lines[0].line_id)
    fireEvent.click(await screen.findByRole('button', { name: 'Replace' }))
    expect(onReplace).toHaveBeenCalledWith(lines[0].line_id)
  })

  it('has a close button', async () => {
    setup(lines[0].line_id)
    const dialog = await screen.findByRole('dialog')
    const buttons = within(dialog).getAllByRole('button', { name: 'Close' })
    fireEvent.click(buttons[buttons.length - 1])
    expect(onClose).toHaveBeenCalled()
  })

  it('is read-only for an estimator: no Confirm or Replace', async () => {
    setup(lines[0].line_id, { canAct: false })
    expect(await screen.findByRole('dialog')).toHaveTextContent('AED 120')
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Replace' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Close' }).length).toBeGreaterThan(0)
  })

  it('disables Confirm once the line is confirmed', async () => {
    lines = [agentLine({ agent_confirmed_by: 'u1', agent_confirmed_at: '2026-10-02T08:00:00Z' })]
    setup(lines[0].line_id)
    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeDisabled()
    expect(screen.getByRole('dialog')).toHaveTextContent('Confirmed on 2026-10-02')
  })
})
