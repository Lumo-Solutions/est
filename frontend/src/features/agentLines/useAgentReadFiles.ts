import { QueryClient, QueryClientContext, useQuery } from '@tanstack/react-query'
import { useContext, useMemo } from 'react'
import { api } from '../../lib/api'
import type { AgentRunRef, AgentRunSections } from './types'

// Used only when there is no QueryClientProvider: the hook then stays idle and returns an empty set.
const idleClient = new QueryClient()
const EMPTY: ReadonlySet<string> = new Set()
const CACHE = { staleTime: 5 * 60_000, retry: false, refetchOnWindowFocus: false } as const

/** File ids the latest agent run read: the union of sections[].coverage.files_read[].file_id.
 * One query pair, cached, no polling. Without a run (or on any error) the set is empty. */
export function useAgentReadFiles(projectId: string | undefined): ReadonlySet<string> {
  const provided = useContext(QueryClientContext)
  const client = provided ?? idleClient
  const enabled = Boolean(projectId) && provided !== undefined

  const runs = useQuery(
    {
      queryKey: ['agent-lines', 'runs', projectId],
      queryFn: ({ signal }) => api.get<AgentRunRef[]>(`/projects/${projectId}/agent/runs`, signal),
      enabled,
      ...CACHE,
    },
    client,
  )
  const latestId = runs.data?.[0]?.id
  const detail = useQuery(
    {
      queryKey: ['agent-lines', 'run', latestId],
      queryFn: ({ signal }) => api.get<AgentRunSections>(`/agent/runs/${latestId}`, signal),
      enabled: enabled && Boolean(latestId),
      ...CACHE,
    },
    client,
  )

  return useMemo(() => {
    const sections = detail.data?.sections
    if (!sections) return EMPTY
    const ids = new Set<string>()
    for (const s of sections) for (const f of s.coverage?.files_read ?? []) ids.add(f.file_id)
    return ids.size > 0 ? ids : EMPTY
  }, [detail.data])
}
