import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let roles: string[] = []
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

import { MeasureAll } from './MeasureAll'

const counts = (o: Record<string, number> = {}) => ({ indexed: 0, queued: 0, measuring: 0, measured: 0, failed: 0, ...o })

function mockFetch(summary: unknown) {
  const posts: { url: string; body: unknown }[] = []
  const json = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return json({ matched: 7, queued: 5, measuring: 1, measured: 1, skipped: 0 }, 202)
      }
      if (url.endsWith('/projects/p1/drawings/measurement-summary')) return json(summary)
      return json({}, 404)
    }),
  )
  return posts
}

const SUMMARY = {
  total: counts({ indexed: 5, measured: 2, failed: 1 }),
  by_discipline: {
    roads_civil: counts({ indexed: 3, failed: 1 }),
    stormwater: counts({ indexed: 2 }),
    structural: counts({ measured: 2 }),
  },
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MeasureAll projectId="p1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  roles = ['lead_estimator']
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('MeasureAll', () => {
  it('shows the counts and only disciplines with indexed or failed drawings', async () => {
    mockFetch(SUMMARY)
    renderCard()
    expect(await screen.findByText('Drawings to measure')).toBeInTheDocument()
    expect(screen.getByText('Not measured').nextSibling).toHaveTextContent('5')
    expect(screen.getByText('Measured').nextSibling).toHaveTextContent('2')
    expect(screen.getByText('Failed').nextSibling).toHaveTextContent('1')
    expect(screen.getByRole('checkbox', { name: /Roads \/ civil/ })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Stormwater/ })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /Structural/ })).toBeNull()
  })

  it('an estimator sees the counts but no button', async () => {
    roles = ['estimator']
    mockFetch(SUMMARY)
    renderCard()
    await screen.findByText('Drawings to measure')
    expect(screen.queryByRole('button', { name: 'Measure selected' })).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('a lead posts the chosen disciplines and sees the result', async () => {
    const posts = mockFetch(SUMMARY)
    renderCard()
    const button = await screen.findByRole('button', { name: 'Measure selected' })
    expect(button).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: /Roads \/ civil/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Stormwater/ }))
    fireEvent.click(button)
    expect(await screen.findByText('Queued 5 drawings (2 already measured or running)')).toBeInTheDocument()
    expect(posts).toEqual([
      { url: '/api/v1/projects/p1/drawings/measure', body: { disciplines: ['roads_civil', 'stormwater'] } },
    ])
  })

  it('polls the summary every 5 s while drawings are queued or measuring', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    mockFetch({ total: counts({ queued: 2, measuring: 1 }), by_discipline: {} })
    renderCard()
    await screen.findByText('Drawings to measure')
    const fetchMock = vi.mocked(fetch)
    const first = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(5200)
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(first))
    expect(screen.getByRole('status')).toHaveTextContent('Measuring in progress')
  })

  it('renders nothing for a project without drawings', async () => {
    mockFetch({ total: counts(), by_discipline: {} })
    const { container } = renderCard()
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
