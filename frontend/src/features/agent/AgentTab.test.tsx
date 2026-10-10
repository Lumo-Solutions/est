import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentTab } from './AgentTab'
import type { AgentRunDetail, AgentSection, AgentStep, ChatMessage } from './types'

const get = vi.fn()
const post = vi.fn()
vi.mock('../../lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}))
let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const conflict = (message: string) => Object.assign(new Error(message), { status: 409 })

const section = (over: Partial<AgentSection> = {}): AgentSection => ({
  id: 'sec1',
  section_item_id: 'item1',
  label: '03 Concrete',
  seq: 1,
  status: 'done',
  line_count: 10,
  steps: 4,
  plan: null,
  summary: null,
  coverage: null,
  stop_reason: null,
  error: null,
  started_at: null,
  finished_at: null,
  ...over,
})

const run = (over: Partial<AgentRunDetail> = {}): AgentRunDetail => ({
  id: 'r1',
  project_id: 'p1',
  kind: 'run',
  settlement_id: 's1',
  status: 'running',
  scope: {},
  limits: { max_steps: 200, max_page_views: 80, max_usd: 5 },
  estimate: null,
  plan: { summary: 'Read the structural drawings first.', sections: [{ section_id: 'sec1', folders: ['/Structural'], queries: ['slab thickness'], why: 'Largest section' }] },
  summary: null,
  provider: 'anthropic',
  steps_total: 12,
  page_views: 7,
  ai_calls: 12,
  cost_usd: 0.42,
  error: null,
  started_by: 'u1',
  confirmed_by: null,
  confirmed_at: null,
  started_at: null,
  finished_at: null,
  created_at: '2026-01-01T00:00:00Z',
  sections: [section()],
  ...over,
})

const step = (over: Partial<AgentStep> = {}): AgentStep => ({
  id: 'st1',
  run_id: 'r1',
  section_id: 'sec1',
  seq: 1,
  tool: 'read_text',
  args: {},
  note: 'Checking the slab detail',
  ok: true,
  result_summary: 'Read 2 pages',
  file_refs: [{ document_id: 'doc9', filename: 'S-101.pdf', page: 3 }],
  tokens_in: 0,
  tokens_out: 0,
  cost_usd: 0,
  injection: false,
  created_at: '2026-01-01T00:00:00Z',
  ...over,
})

let current: AgentRunDetail
let stepList: AgentStep[]
let messages: ChatMessage[]
let conversations: Array<{ id: string; title: string | null; created_at: string }>

function setup(role: string, opts: { runs?: boolean } = {}) {
  roles = [role]
  get.mockImplementation((path: string) => {
    if (path === '/projects/p1/agent/runs') return Promise.resolve(opts.runs === false ? [] : [current])
    if (path === '/agent/runs/r1') return Promise.resolve(current)
    if (path.startsWith('/agent/runs/r1/steps')) {
      const after = Number(/after_seq=(\d+)/.exec(path)?.[1] ?? 0)
      return Promise.resolve(stepList.filter((s) => s.seq > after))
    }
    if (path === '/bid-settlements/s1/agent-summary') return Promise.resolve({ agent_lines: 9, unconfirmed: 7 })
    if (path === '/projects/p1/agent/conversations') return Promise.resolve(conversations)
    if (path.startsWith('/agent/conversations/c1/messages')) return Promise.resolve(messages)
    return Promise.reject(new Error(`unexpected GET ${path}`))
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentTab projectId="p1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const runCalls = () => get.mock.calls.filter((c) => c[0] === '/agent/runs/r1').length

describe('AgentTab', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    post.mockResolvedValue({})
    current = run()
    stepList = [step()]
    messages = []
    conversations = []
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  describe('role gating', () => {
    it('lets a lead start, pause and cancel, and chat', async () => {
      setup('lead_estimator')
      expect(await screen.findByText('Running')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Run estimation agent' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Resume' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Cancel run' })).toBeEnabled()
      expect(screen.getByLabelText('Message to the agent')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
      await waitFor(() => expect(post).toHaveBeenCalledWith('/agent/runs/r1/pause'))
    })

    it('enables Resume only while paused', async () => {
      current = run({ status: 'paused' })
      setup('procurement_head')
      expect(await screen.findByText('Paused')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
      fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
      await waitFor(() => expect(post).toHaveBeenCalledWith('/agent/runs/r1/resume'))
    })

    it.each(['bd_director', 'managing_director'])('treats %s as a lead for the run button', async (r) => {
      setup(r)
      expect(await screen.findByRole('button', { name: 'Run estimation agent' })).toBeEnabled()
    })

    it('shows an estimator everything read-only, with the reason', async () => {
      setup('estimator')
      expect(await screen.findByText('Running')).toBeInTheDocument()
      const runBtn = screen.getByRole('button', { name: 'Run estimation agent' })
      expect(runBtn).toBeDisabled()
      expect(runBtn).toHaveAccessibleDescription(/lead estimator/)
      expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument()
      expect(screen.queryByLabelText('Message to the agent')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'New chat' })).not.toBeInTheDocument()
      expect(screen.getByText(/Read-only/)).toBeInTheDocument()
      expect(post).not.toHaveBeenCalled()
    })
  })

  describe('starting a run', () => {
    it('shows the estimate and starts nothing until Confirm', async () => {
      setup('lead_estimator', { runs: false })
      post.mockResolvedValueOnce(
        run({
          status: 'awaiting_confirm',
          estimate: {
            provider: 'anthropic',
            model: 'claude-x',
            external: true,
            sections: 5,
            steps: 120,
            page_views: 40,
            usd: 1.5,
            usd_uncapped: 2,
            usd_cap: 3,
            unverified_price: true,
            note: null,
          },
        }),
      )
      fireEvent.click(await screen.findByRole('button', { name: 'Run estimation agent' }))
      const dialog = await screen.findByRole('dialog', { name: 'Estimated agent cost' })
      expect(post).toHaveBeenCalledTimes(1)
      expect(post).toHaveBeenCalledWith('/projects/p1/agent/runs', {})
      for (const t of ['anthropic', 'claude-x', '120', '40', '$1.50', '$3.00']) {
        expect(within(dialog).getByText(t)).toBeInTheDocument()
      }
      expect(within(dialog).getByText(/Price not yet verified/)).toBeInTheDocument()
      // Focus moved into the dialog, and nothing was confirmed yet.
      expect(dialog.contains(document.activeElement)).toBe(true)
      expect(post).not.toHaveBeenCalledWith('/agent/runs/r1/confirm')
      fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm and start' }))
      await waitFor(() => expect(post).toHaveBeenCalledWith('/agent/runs/r1/confirm'))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('Cancel in the estimate dialog never confirms and releases the waiting run', async () => {
      setup('lead_estimator', { runs: false })
      post.mockResolvedValueOnce(run({ status: 'awaiting_confirm', estimate: null }))
      fireEvent.click(await screen.findByRole('button', { name: 'Run estimation agent' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      await waitFor(() => expect(post).toHaveBeenCalledWith('/agent/runs/r1/cancel'))
      expect(post).not.toHaveBeenCalledWith('/agent/runs/r1/confirm')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('closes the dialog on Escape', async () => {
      setup('lead_estimator', { runs: false })
      post.mockResolvedValueOnce(run({ status: 'awaiting_confirm' }))
      fireEvent.click(await screen.findByRole('button', { name: 'Run estimation agent' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.keyDown(dialog, { key: 'Escape' })
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(post).not.toHaveBeenCalledWith('/agent/runs/r1/confirm')
    })

    it('shows the server message on a 409 for an active run', async () => {
      setup('lead_estimator', { runs: false })
      post.mockRejectedValueOnce(conflict('A run is already active for this project.'))
      fireEvent.click(await screen.findByRole('button', { name: 'Run estimation agent' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('A run is already active for this project.')
      expect(screen.queryByRole('button', { name: 'Start a new draft version' })).not.toBeInTheDocument()
    })

    it('offers a new draft version when the settlement is not a draft, and sends create_draft', async () => {
      setup('lead_estimator', { runs: false })
      post.mockRejectedValueOnce(conflict('The current settlement is not a draft.'))
      fireEvent.click(await screen.findByRole('button', { name: 'Run estimation agent' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('not a draft')
      post.mockResolvedValueOnce(run({ status: 'queued' }))
      fireEvent.click(screen.getByRole('button', { name: 'Start a new draft version' }))
      await waitFor(() => expect(post).toHaveBeenLastCalledWith('/projects/p1/agent/runs', { create_draft: true }))
    })

    it('shows an empty state when there is no run yet', async () => {
      setup('lead_estimator', { runs: false })
      expect(await screen.findByText(/No agent run yet/)).toBeInTheDocument()
    })
  })

  describe('progress and polling', () => {
    it('shows cost against the cap, counters, and a row per section with the stop reason', async () => {
      current = run({
        sections: [
          section(),
          section({ id: 'sec2', label: '05 Steel', seq: 2, status: 'stopped_limit', stop_reason: 'budget', steps: 9 }),
          section({ id: 'sec3', label: '07 MEP', seq: 3, status: 'pending', steps: 0 }),
        ],
      })
      setup('lead_estimator')
      expect(await screen.findByText('$0.42 / $5.00')).toBeInTheDocument()
      expect(screen.getByText('12 / 200')).toBeInTheDocument()
      expect(screen.getByText('7 / 80')).toBeInTheDocument()
      const rows = within(screen.getByRole('list', { name: 'Sections' })).getAllByRole('listitem')
      expect(rows).toHaveLength(3)
      expect(rows[1]).toHaveTextContent('05 Steel')
      expect(rows[1]).toHaveTextContent('Stopped at the budget limit')
      expect(rows[1]).toHaveTextContent('9 steps')
      expect(rows[2]).toHaveTextContent('Pending')
    })

    it('polls while running and stops once the run is terminal', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      setup('lead_estimator')
      expect(await screen.findByText('Running')).toBeInTheDocument()
      const before = runCalls()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2600)
      })
      expect(runCalls()).toBeGreaterThan(before)

      current = run({ status: 'done' })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2600)
      })
      expect((await screen.findAllByText('Done')).length).toBeGreaterThan(1)
      const settled = runCalls()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(40000)
      })
      expect(runCalls()).toBe(settled)
    })
  })

  describe('trace', () => {
    it('renders the plan, each step with a human tool label and page-anchored file links', async () => {
      setup('lead_estimator')
      expect(await screen.findByText('Read the structural drawings first.')).toBeInTheDocument()
      expect(screen.getByText('slab thickness')).toBeInTheDocument()
      const steps = Array.from((await screen.findByRole('list', { name: 'Agent steps' })).children) as HTMLElement[]
      expect(steps).toHaveLength(1)
      expect(steps[0]).toHaveTextContent('Read text')
      expect(steps[0]).toHaveTextContent('Checking the slab detail')
      expect(steps[0]).toHaveTextContent('Read 2 pages')
      expect(steps[0]).toHaveTextContent('OK')
      const link = within(steps[0]).getByRole('link', { name: /S-101\.pdf p\.3/ })
      expect(link).toHaveAttribute('href', '/api/v1/tender-documents/doc9/download#page=3')
      expect(link).toHaveAttribute('target', '_blank')
      expect(screen.queryByText(/Instruction-like text/)).not.toBeInTheDocument()
    })

    it('badges a step whose file looked like instructions, and an errored step', async () => {
      stepList = [step(), step({ id: 'st2', seq: 2, tool: 'search_files', ok: false, injection: true, file_refs: [] })]
      setup('estimator')
      expect(await screen.findByText(/Instruction-like text was found in this file/)).toBeInTheDocument()
      expect(screen.getByText('Error')).toBeInTheDocument()
      expect(screen.getByText('Search files')).toBeInTheDocument()
    })

    it('filters by section and loads later steps with after_seq', async () => {
      stepList = [step(), step({ id: 'st2', seq: 2, section_id: 'sec2', tool: 'view_page', note: 'Steel page', file_refs: [] })]
      current = run({ sections: [section(), section({ id: 'sec2', label: '05 Steel', seq: 2 })] })
      vi.useFakeTimers({ shouldAdvanceTime: true })
      setup('lead_estimator')
      expect(await screen.findByText('Steel page')).toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('Filter by section'), { target: { value: 'sec1' } })
      expect(screen.queryByText('Steel page')).not.toBeInTheDocument()
      expect(screen.getByText('Checking the slab detail')).toBeInTheDocument()

      stepList = [...stepList, step({ id: 'st3', seq: 3, note: 'A later step', file_refs: [] })]
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2600)
      })
      expect(await screen.findByText('A later step')).toBeInTheDocument()
      const urls = get.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith('/agent/runs/r1/steps'))
      expect(urls[0]).toContain('after_seq=0')
      expect(urls.some((u) => u.includes('after_seq=2'))).toBe(true)
    })
  })

  describe('coverage and summary', () => {
    it('expands a section to show files read, files not read and line counts', async () => {
      current = run({
        sections: [
          section({
            coverage: {
              files_read: [{ file_id: 'f1', path: '/Structural/S-101.pdf', pages: [2, 3] }],
              found_not_read: [{ file_id: 'f2', path: '/Spec/Concrete.pdf', why_found: 'matches concrete', why_not_read: 'step limit' }],
              lines_total: 10,
              lines_proposed: 7,
              lines_without_proposal: ['l1', 'l2', 'l3'],
              lines_cost_source_only: 2,
            },
          }),
        ],
      })
      setup('estimator')
      const toggle = await screen.findByRole('button', { name: '03 Concrete' })
      expect(toggle).toHaveAttribute('aria-expanded', 'false')
      expect(screen.queryByText('/Structural/S-101.pdf (pages 2, 3)')).not.toBeInTheDocument()
      fireEvent.click(toggle)
      expect(toggle).toHaveAttribute('aria-expanded', 'true')
      expect(screen.getByText(/\/Structural\/S-101\.pdf/)).toHaveTextContent('pages 2, 3')
      expect(screen.getByText(/\/Spec\/Concrete\.pdf/)).toHaveTextContent('not read: step limit')
      expect(screen.getByText(/3 of 10 lines without a proposal/)).toHaveTextContent('2 priced from a cost source only')
    })

    it('summarises a finished run and links to the settlement with the unconfirmed count', async () => {
      current = run({
        status: 'done',
        cost_usd: 1.23,
        summary: { proposals: 40, applied: { applied: 33, skipped_person_set: 4 }, files_read: 12, files_in_pack: 80, seconds: 125 },
      })
      setup('estimator')
      expect(await screen.findByText('Run summary')).toBeInTheDocument()
      expect(screen.getByText('40')).toBeInTheDocument()
      expect(screen.getByText('33')).toBeInTheDocument()
      expect(screen.getByText('4')).toBeInTheDocument()
      expect(screen.getByText('12 of 80')).toBeInTheDocument()
      expect(screen.getByText('2 min 5 s')).toBeInTheDocument()
      expect(screen.getByText('$1.23')).toBeInTheDocument()
      const link = await screen.findByRole('link', { name: '7 lines need your confirmation before submit' })
      expect(link).toHaveAttribute('href', '/projects/p1/settlement')
    })

    it('does not show a summary while the run is active', async () => {
      setup('estimator')
      await screen.findByText('Running')
      expect(screen.queryByText('Run summary')).not.toBeInTheDocument()
    })
  })

  describe('chat', () => {
    const msg = (over: Partial<ChatMessage>): ChatMessage => ({
      id: 'm1',
      conversation_id: 'c1',
      role: 'user',
      content: 'hello',
      run_id: null,
      created_at: '2026-01-01T00:00:01Z',
      ...over,
    })

    it('shows the latest conversation by default, read-only for an estimator', async () => {
      conversations = [{ id: 'c1', title: 'Pricing questions', created_at: '2026-01-01T00:00:00Z' }]
      messages = [msg({ content: 'why this rate?' }), msg({ id: 'm2', role: 'assistant', content: 'From quotation Q-1', created_at: '2026-01-01T00:00:02Z' })]
      setup('estimator')
      expect(await screen.findByText('why this rate?')).toBeInTheDocument()
      expect(screen.getByText('From quotation Q-1')).toBeInTheDocument()
      expect(screen.getByLabelText('Conversation')).toHaveValue('c1')
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    it('sends a message, shows the agent is working, polls with after= and stops on the reply', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      conversations = [{ id: 'c1', title: null, created_at: '2026-01-01T00:00:00Z' }]
      messages = []
      setup('lead_estimator')
      const input = await screen.findByLabelText('Message to the agent')
      fireEvent.change(input, { target: { value: 'what is left?' } })
      post.mockImplementationOnce(() => {
        const m = msg({ id: 'm1', content: 'what is left?' })
        messages = [m]
        return Promise.resolve({ conversation_id: 'c1', message: m, run_id: 'cr1' })
      })
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      await waitFor(() =>
        expect(post).toHaveBeenCalledWith('/projects/p1/agent/chat', { message: 'what is left?', conversation_id: 'c1' }),
      )
      expect(await screen.findByRole('status')).toHaveTextContent('The agent is working')
      expect(input).toHaveValue('')

      messages = [msg({ id: 'm1', content: 'what is left?' }), msg({ id: 'm2', role: 'assistant', content: 'Two sections.', created_at: '2026-01-01T00:00:05Z' })]
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100)
      })
      expect(await screen.findByText('Two sections.')).toBeInTheDocument()
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      expect(get.mock.calls.some((c) => String(c[0]).includes('messages?after=2026-01-01T00%3A00%3A01Z'))).toBe(true)

      const polls = () => get.mock.calls.filter((c) => String(c[0]).startsWith('/agent/conversations/c1/messages')).length
      const settled = polls()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000)
      })
      expect(polls()).toBe(settled)
    })

    it('shows the 409 message when a reply is still pending', async () => {
      conversations = [{ id: 'c1', title: null, created_at: '2026-01-01T00:00:00Z' }]
      setup('lead_estimator')
      fireEvent.change(await screen.findByLabelText('Message to the agent'), { target: { value: 'again' } })
      post.mockRejectedValueOnce(conflict('The agent is still answering your last message.'))
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      const alert = await screen.findByText('The agent is still answering your last message.')
      expect(alert).toHaveAttribute('role', 'alert')
    })

    it('"New chat" sends without a conversation id', async () => {
      conversations = [{ id: 'c1', title: 'Old', created_at: '2026-01-01T00:00:00Z' }]
      messages = [msg({ role: 'assistant', content: 'old answer' })]
      setup('lead_estimator')
      expect(await screen.findByText('old answer')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
      expect(screen.queryByText('old answer')).not.toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('Message to the agent'), { target: { value: 'fresh' } })
      post.mockResolvedValueOnce({ conversation_id: 'c2', message: msg({ id: 'n1', conversation_id: 'c2', content: 'fresh' }), run_id: 'cr2' })
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      await waitFor(() => expect(post).toHaveBeenCalledWith('/projects/p1/agent/chat', { message: 'fresh', conversation_id: undefined }))
    })

    it('collapses', async () => {
      setup('lead_estimator')
      const toggle = await screen.findByRole('button', { name: 'Chat with the agent' })
      fireEvent.click(toggle)
      expect(toggle).toHaveAttribute('aria-expanded', 'false')
      expect(screen.queryByLabelText('Message to the agent')).not.toBeInTheDocument()
    })
  })

  it('shows a load error with Retry', async () => {
    roles = ['lead_estimator']
    get.mockRejectedValue(new Error('boom'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AgentTab projectId="p1" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const alerts = await screen.findAllByRole('alert')
    expect(alerts[0]).toHaveTextContent('boom')
    expect(screen.getAllByRole('button', { name: 'Retry' }).length).toBeGreaterThan(0)
  })
})
