import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AiStatusNotice } from './AiStatusNotice'
import type { AiStatusOut } from '../../types/api'

const get = vi.fn()
vi.mock('../../lib/api', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

const base: AiStatusOut = {
  provider: 'openai',
  external: true,
  configured: true,
  external_ai_allowed: true,
  available: true,
  message: null,
}

function renderNotice() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AiStatusNotice />
    </QueryClientProvider>,
  )
}

describe('AiStatusNotice', () => {
  beforeEach(() => get.mockReset())

  it('shows the message when AI is not available', async () => {
    get.mockResolvedValue({ ...base, configured: false, available: false, message: 'AI not configured' })
    renderNotice()
    expect(await screen.findByRole('status')).toHaveTextContent('AI not configured')
  })

  it('renders nothing when AI is available', async () => {
    get.mockResolvedValue(base)
    const { container } = renderNotice()
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
