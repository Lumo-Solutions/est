import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { itemPage, treeItem, treeOut, treeSummary } from './testFixtures'
import type { TreeOut } from './types'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../lib/api', () => ({ api: { get, post } }))

import {
  countsSignature,
  useBulkConfirm,
  useBulkReclassify,
  useCancelTenderPackage,
  usePauseTenderPackage,
  useReclassifyDocument,
  useResumeTenderPackage,
  useTenderItems,
  useTenderTree,
} from './api'

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return { qc, wrapper }
}

function intervalFor(qc: QueryClient, summary: ReturnType<typeof treeSummary> | undefined) {
  const query = qc.getQueryCache().find({ queryKey: ['tender-tree', 'p1'] })
  if (!query) throw new Error('tree query not found')
  const fn = (query.options as unknown as { refetchInterval: (q: { state: { data: unknown } }) => number | false }).refetchInterval
  return fn({ state: { data: summary ? treeOut({ summary }) : undefined } })
}

describe('tender tree api hooks', () => {
  it('fetches the counts payload and polls the summary every 2 s only while something is uploading or being read', async () => {
    get.mockResolvedValue(treeOut())
    const { qc, wrapper } = setup()
    const { result } = renderHook(() => useTenderTree('p1'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(get.mock.calls[0][0]).toBe('/projects/p1/tender-documents/tree')
    expect(result.current.data).not.toHaveProperty('items')
    expect(intervalFor(qc, treeSummary({ in_progress: 3 }))).toBe(2000)
    expect(intervalFor(qc, treeSummary({ pending_upload: 5 }))).toBe(2000)
    expect(intervalFor(qc, treeSummary({ packages_processing: 1 }))).toBe(2000)
    expect(intervalFor(qc, treeSummary())).toBe(false)
    expect(intervalFor(qc, undefined)).toBe(false)
  })

  it('refreshes the open item lists when the counts move, but at most once per 5 s', async () => {
    get.mockResolvedValue(treeOut({ summary: treeSummary({ total: 10, in_progress: 5, by_display_status: { reading: 5, ready: 5 } }) }))
    const { qc, wrapper } = setup()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useTenderTree('p1'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const itemCalls = () => invalidate.mock.calls.filter((c) => JSON.stringify(c[0]) === JSON.stringify({ queryKey: ['tender-items', 'p1'] })).length
    // The first load is not a change.
    expect(itemCalls()).toBe(0)

    const next = (ready: number): TreeOut => treeOut({ summary: treeSummary({ total: 10, in_progress: 10 - ready, by_display_status: { reading: 10 - ready, ready } }) })
    act(() => {
      qc.setQueryData(['tender-tree', 'p1'], next(6))
    })
    await waitFor(() => expect(itemCalls()).toBe(1))
    // Counts keep moving inside the 5 s window: no second refresh yet (it is scheduled for later).
    act(() => {
      qc.setQueryData(['tender-tree', 'p1'], next(7))
    })
    act(() => {
      qc.setQueryData(['tender-tree', 'p1'], next(8))
    })
    await new Promise((r) => setTimeout(r, 50))
    expect(itemCalls()).toBe(1)
  })

  it('the counts signature changes with the per-status counts and not with unrelated fields', () => {
    const a = treeSummary({ total: 10, by_display_status: { reading: 5, ready: 5 } })
    expect(countsSignature(a)).toBe(countsSignature(treeSummary({ total: 10, by_display_status: { ready: 5, reading: 5 }, ai_available: false })))
    expect(countsSignature(a)).not.toBe(countsSignature(treeSummary({ total: 10, by_display_status: { reading: 4, ready: 6 } })))
  })

  it('pages /items 100 at a time with the filter as query params, following the total', async () => {
    const first = Array.from({ length: 100 }, () => treeItem())
    get.mockReset()
    get.mockResolvedValueOnce(itemPage(first, 150, 0)).mockResolvedValueOnce(itemPage(Array.from({ length: 50 }, () => treeItem()), 150, 100))
    const { wrapper } = setup()
    const { result } = renderHook(() => useTenderItems('p1', { doc_class: 'drawing', discipline: 'none', q: 'rd 1' }), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(get.mock.calls[0][0]).toBe('/projects/p1/tender-documents/items?doc_class=drawing&discipline=none&q=rd+1&limit=100&offset=0')
    expect(result.current.hasNextPage).toBe(true)
    await act(async () => {
      await result.current.fetchNextPage()
    })
    expect(get.mock.calls[1][0]).toContain('limit=100&offset=100')
    await waitFor(() => expect(result.current.hasNextPage).toBe(false))
  })

  it('sends exclude_flags as a repeated param, has_class, and the top-level folder as folder=', async () => {
    get.mockReset()
    get.mockResolvedValue(itemPage([], 0))
    const { wrapper } = setup()
    const a = renderHook(() => useTenderItems('p1', { display_status: 'needs_check', has_class: true, exclude_flags: ['conflict', 'injection_suspected'] }, { limit: 1 }), { wrapper })
    await waitFor(() => expect(a.result.current.isSuccess).toBe(true))
    expect(get.mock.calls[0][0]).toBe(
      '/projects/p1/tender-documents/items?display_status=needs_check&has_class=true&exclude_flags=conflict&exclude_flags=injection_suspected&limit=1&offset=0',
    )
    const b = renderHook(() => useTenderItems('p1', { folder: '' }), { wrapper })
    await waitFor(() => expect(b.result.current.isSuccess).toBe(true))
    expect(get.mock.calls[1][0]).toBe('/projects/p1/tender-documents/items?folder=&limit=100&offset=0')
  })

  it('does not fetch while disabled or without a filter', () => {
    get.mockReset()
    const { wrapper } = setup()
    renderHook(() => useTenderItems('p1', { q: 'x' }, { enabled: false }), { wrapper })
    renderHook(() => useTenderItems('p1', null), { wrapper })
    expect(get).not.toHaveBeenCalled()
  })

  it('reclassify posts the body with confirm and refreshes the tree and the item lists', async () => {
    post.mockResolvedValue({})
    const { qc, wrapper } = setup()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useReclassifyDocument('p1'), { wrapper })
    await result.current.mutateAsync({ id: 'd1', doc_class: 'drawing', sub_type: 'sewer', drawing_type: 'plan_profile', confirm: true })
    expect(post).toHaveBeenCalledWith('/tender-documents/d1/reclassify', { doc_class: 'drawing', sub_type: 'sewer', drawing_type: 'plan_profile', confirm: true })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tender-tree', 'p1'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tender-items', 'p1'] })
  })

  it('bulk reclassify posts ids or a filter with a cursor to the project endpoint', async () => {
    post.mockResolvedValue({ confirmed: 2, failed: 0, skipped: 0, results: [] })
    const { wrapper } = setup()
    const { result } = renderHook(() => useBulkReclassify('p1'), { wrapper })
    await result.current.mutateAsync({ document_ids: ['a', 'b'], doc_class: 'boq', confirm: true })
    expect(post).toHaveBeenCalledWith('/projects/p1/tender-documents/bulk-reclassify', { document_ids: ['a', 'b'], doc_class: 'boq', confirm: true })
    await result.current.mutateAsync({ filter: { doc_class: 'drawing' }, cursor: 'c1', doc_class: 'boq', confirm: true })
    expect(post).toHaveBeenLastCalledWith('/projects/p1/tender-documents/bulk-reclassify', { filter: { doc_class: 'drawing' }, cursor: 'c1', doc_class: 'boq', confirm: true })
  })

  it('bulk confirm posts the filter and cursor; quiet mode skips the per-chunk refresh', async () => {
    post.mockResolvedValue({ confirmed: 1, failed: 0, skipped: 0, results: [], matched: 1, next_cursor: null })
    const { qc, wrapper } = setup()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const quiet = renderHook(() => useBulkConfirm('p1', { quiet: true }), { wrapper })
    await quiet.result.current.mutateAsync({ filter: { display_status: 'needs_check' }, cursor: null })
    expect(post).toHaveBeenLastCalledWith('/projects/p1/tender-documents/bulk-confirm', { filter: { display_status: 'needs_check' }, cursor: null })
    expect(invalidate).not.toHaveBeenCalled()
    const loud = renderHook(() => useBulkConfirm('p1'), { wrapper })
    await loud.result.current.mutateAsync({ document_ids: ['a'] })
    expect(invalidate).toHaveBeenCalled()
  })

  it('pause, resume and cancel post to the pack endpoints and refresh the intake queries', async () => {
    post.mockResolvedValue({ package_id: 'pk1', status: 'paused', cancelled_documents: 0 })
    const { qc, wrapper } = setup()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const pause = renderHook(() => usePauseTenderPackage('p1'), { wrapper })
    const resume = renderHook(() => useResumeTenderPackage('p1'), { wrapper })
    const cancel = renderHook(() => useCancelTenderPackage('p1'), { wrapper })
    await pause.result.current.mutateAsync('pk1')
    expect(post).toHaveBeenLastCalledWith('/tender-packages/pk1/pause')
    await resume.result.current.mutateAsync('pk1')
    expect(post).toHaveBeenLastCalledWith('/tender-packages/pk1/resume')
    await cancel.result.current.mutateAsync('pk1')
    expect(post).toHaveBeenLastCalledWith('/tender-packages/pk1/cancel')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tender-tree', 'p1'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tender-packages', 'p1'] })
  })
})
