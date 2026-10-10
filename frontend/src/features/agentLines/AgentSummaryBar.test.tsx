import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentSourceBadge } from './AgentBadges'
import { AgentSummaryBar } from './AgentSummaryBar'
import { agentLine, estimateLine } from './fixtures'
import { bulkResultText } from './text'

const post = vi.fn()
vi.mock('../../lib/api', async (orig) => ({
  ...(await orig<typeof import('../../lib/api')>()),
  api: { post: (...a: unknown[]) => post(...a) },
}))

const onReview = vi.fn()
function setup(props: { unconfirmed: number; canAct?: boolean; draft?: boolean }) {
  const client = new QueryClient()
  const ui = (unconfirmed: number) => (
    <QueryClientProvider client={client}>
      <AgentSummaryBar
        settlementId="s1"
        summary={{ agent_lines: 5, unconfirmed }}
        draft={props.draft ?? true}
        canAct={props.canAct ?? true}
        reviewing={false}
        onReview={onReview}
      />
    </QueryClientProvider>
  )
  const view = render(ui(props.unconfirmed))
  return { rerenderWith: (n: number) => view.rerender(ui(n)) }
}

describe('AgentSummaryBar', () => {
  beforeEach(() => {
    post.mockReset()
    onReview.mockReset()
  })

  it('shows the count and goes away when nothing is left', () => {
    const { rerenderWith } = setup({ unconfirmed: 3 })
    expect(screen.getByRole('status')).toHaveTextContent('3 agent lines need confirmation before submit')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(onReview).toHaveBeenCalled()
    rerenderWith(1)
    expect(screen.getByRole('status')).toHaveTextContent('1 agent line needs confirmation before submit')
    rerenderWith(0)
    expect(screen.queryByText(/need confirmation/)).not.toBeInTheDocument()
  })

  it('shows nothing on a settlement that is not a draft', () => {
    setup({ unconfirmed: 3, draft: false })
    expect(screen.queryByText(/confirmation before submit/)).not.toBeInTheDocument()
  })

  it('bulk confirm shows the result text', async () => {
    post.mockResolvedValue({ confirmed: 12, skipped: { estimate: 3, blocked_or_low_confidence: 2 } })
    setup({ unconfirmed: 17 })
    fireEvent.click(screen.getByRole('button', { name: 'Bulk confirm' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/bid-settlements/s1/agent-confirm-bulk'))
    expect(await screen.findByText('12 confirmed; 3 estimates and 2 low-confidence or blocked lines need one-by-one review')).toBeInTheDocument()
  })

  it('has no actions for an estimator, only Review', () => {
    setup({ unconfirmed: 2, canAct: false })
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Bulk confirm' })).not.toBeInTheDocument()
  })

  it('words the result for singular and clean runs', () => {
    expect(bulkResultText({ confirmed: 4, skipped: { estimate: 1, blocked_or_low_confidence: 0 } })).toBe('4 confirmed; 1 estimate needs one-by-one review')
    expect(bulkResultText({ confirmed: 4, skipped: { estimate: 0, blocked_or_low_confidence: 0 } })).toBe('4 confirmed')
  })
})

describe('AgentSourceBadge', () => {
  it('names the source of each kind of agent line and "Confirmed" once confirmed', () => {
    const { rerender } = render(<AgentSourceBadge line={agentLine()} />)
    expect(screen.getByText('Agent: source')).toBeInTheDocument()
    rerender(<AgentSourceBadge line={estimateLine()} />)
    expect(screen.getByText('Agent: estimate')).toBeInTheDocument()
    rerender(<AgentSourceBadge line={agentLine({ agent_confirmed_by: 'u1' })} />)
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
  })
})
