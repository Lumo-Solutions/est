import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentReadFiles } from './useAgentReadFiles'

const get = vi.fn()
vi.mock('../../lib/api', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

let client = new QueryClient()
const wrap = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

describe('useAgentReadFiles', () => {
  beforeEach(() => {
    get.mockReset()
    client = new QueryClient()
  })

  it('takes the union of files_read over the sections of the first (latest) run', async () => {
    get.mockImplementation((path: string) => {
      if (path === '/projects/p1/agent/runs') return Promise.resolve([{ id: 'r2' }, { id: 'r1' }])
      if (path === '/agent/runs/r2')
        return Promise.resolve({
          sections: [
            { coverage: { files_read: [{ file_id: 'a' }, { file_id: 'b' }] } },
            { coverage: { files_read: [{ file_id: 'b' }, { file_id: 'c' }] } },
            { coverage: null },
          ],
        })
      return Promise.reject(new Error(path))
    })
    const { result } = renderHook(() => useAgentReadFiles('p1'), { wrapper: wrap })
    await waitFor(() => expect([...result.current].sort()).toEqual(['a', 'b', 'c']))
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('is empty without a run and fetches no detail', async () => {
    get.mockResolvedValue([])
    const { result } = renderHook(() => useAgentReadFiles('p1'), { wrapper: wrap })
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1))
    expect(result.current.size).toBe(0)
  })

  it('stays idle without a query provider', () => {
    const { result } = renderHook(() => useAgentReadFiles('p1'))
    expect(result.current.size).toBe(0)
    expect(get).not.toHaveBeenCalled()
  })
})
