import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { treeSummary } from './testFixtures'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../lib/api', () => ({ api: { get, post } }))

import { useBulkReclassify, useReclassifyDocument, useTenderTree } from './api'

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return { qc, wrapper }
}

function intervalFor(qc: QueryClient, summary: ReturnType<typeof treeSummary> | undefined) {
  const query = qc.getQueryCache().find({ queryKey: ['tender-tree', 'p1'] })
  if (!query) throw new Error('tree query not found')
  const fn = (query.options as unknown as { refetchInterval: (q: { state: { data: unknown } }) => number | false }).refetchInterval
  return fn({ state: { data: summary ? { items: [], summary } : undefined } })
}

describe('tender tree api hooks', () => {
  it('fetches the tree and polls every 2 s only while something is in progress', async () => {
    get.mockResolvedValue({ items: [], summary: treeSummary() })
    const { qc, wrapper } = setup()
    const { result } = renderHook(() => useTenderTree('p1'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(get.mock.calls[0][0]).toBe('/projects/p1/tender-documents/tree')
    expect(intervalFor(qc, treeSummary({ in_progress: 3 }))).toBe(2000)
    expect(intervalFor(qc, treeSummary({ packages_processing: 1 }))).toBe(2000)
    expect(intervalFor(qc, treeSummary())).toBe(false)
    expect(intervalFor(qc, undefined)).toBe(false)
  })

  it('reclassify posts the body with confirm and refreshes the tree', async () => {
    post.mockResolvedValue({})
    const { qc, wrapper } = setup()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useReclassifyDocument('p1'), { wrapper })
    await result.current.mutateAsync({ id: 'd1', doc_class: 'drawing', sub_type: 'sewer', drawing_type: 'plan_profile', confirm: true })
    expect(post).toHaveBeenCalledWith('/tender-documents/d1/reclassify', { doc_class: 'drawing', sub_type: 'sewer', drawing_type: 'plan_profile', confirm: true })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tender-tree', 'p1'] })
  })

  it('bulk reclassify posts to the project endpoint', async () => {
    post.mockResolvedValue({ confirmed: 2, failed: 0, skipped: 0, results: [] })
    const { wrapper } = setup()
    const { result } = renderHook(() => useBulkReclassify('p1'), { wrapper })
    await result.current.mutateAsync({ document_ids: ['a', 'b'], doc_class: 'boq', confirm: true })
    expect(post).toHaveBeenCalledWith('/projects/p1/tender-documents/bulk-reclassify', { document_ids: ['a', 'b'], doc_class: 'boq', confirm: true })
  })
})
