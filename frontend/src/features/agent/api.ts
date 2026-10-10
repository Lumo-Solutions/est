import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import {
  isActive,
  isTerminal,
  type AgentRun,
  type RunAction,
  type AgentRunCreate,
  type AgentRunDetail,
  type AgentStep,
  type AgentSummaryOut,
  type ChatMessage,
  type ChatPostOut,
  type Conversation,
} from './types'

export const RUN_POLL_MS = 2500
export const IDLE_POLL_MS = 15000
export const CHAT_POLL_MS = 2000

const runsKey = (pid: string | undefined) => ['agent', pid, 'runs']

export function useAgentRuns(projectId: string | undefined) {
  return useQuery({
    queryKey: runsKey(projectId),
    queryFn: ({ signal }) => api.get<AgentRun[]>(`/projects/${projectId}/agent/runs`, signal),
    enabled: Boolean(projectId),
  })
}

// 2.5 s while the run is queued/planning/running/awaiting_confirm, 15 s while paused, never once terminal.
export function useAgentRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['agent-run', runId],
    queryFn: ({ signal }) => api.get<AgentRunDetail>(`/agent/runs/${runId}`, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (!s) return false
      return isActive(s) ? RUN_POLL_MS : isTerminal(s) ? false : IDLE_POLL_MS
    },
  })
}

// Steps accumulate in the cache: each poll asks only for seq > the last one we hold.
export function useAgentSteps(runId: string | undefined, status: AgentRun['status'] | undefined) {
  const queryClient = useQueryClient()
  const key = ['agent-run', runId, 'steps']
  const q = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const prev = queryClient.getQueryData<AgentStep[]>(key) ?? []
      const last = prev.length ? prev[prev.length - 1].seq : 0
      const fresh = await api.get<AgentStep[]>(`/agent/runs/${runId}/steps?after_seq=${last}&limit=500`, signal)
      const known = new Set(prev.map((s) => s.seq))
      return [...prev, ...fresh.filter((s) => !known.has(s.seq))]
    },
    enabled: Boolean(runId),
    refetchInterval: () =>
      status && isActive(status) ? RUN_POLL_MS : status && !isTerminal(status) ? IDLE_POLL_MS : false,
  })
  const { refetch } = q
  // One last read when the status moves (e.g. to a terminal one) so the final steps are not missed.
  useEffect(() => {
    if (runId && status) void refetch()
  }, [runId, status, refetch])
  return q
}

export function useAgentSummary(settlementId: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['agent-summary', settlementId],
    queryFn: ({ signal }) => api.get<AgentSummaryOut>(`/bid-settlements/${settlementId}/agent-summary`, signal),
    enabled: Boolean(settlementId) && enabled,
  })
}

export function useStartRun(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AgentRunCreate) => api.post<AgentRunDetail>(`/projects/${projectId}/agent/runs`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runsKey(projectId) }),
  })
}

export function useRunAction(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, action }: { runId: string; action: RunAction }) =>
      api.post<unknown>(`/agent/runs/${runId}/${action}`),
    onSuccess: (_d, v) => {
      void queryClient.invalidateQueries({ queryKey: ['agent-run', v.runId] })
      void queryClient.invalidateQueries({ queryKey: runsKey(projectId) })
    },
  })
}

export function useConversations(projectId: string | undefined) {
  return useQuery({
    queryKey: ['agent', projectId, 'conversations'],
    queryFn: ({ signal }) => api.get<Conversation[]>(`/projects/${projectId}/agent/conversations`, signal),
    enabled: Boolean(projectId),
  })
}

// Messages accumulate (after = created_at of the newest we hold); polls every 2 s while the newest message is the person's.
export function useChatMessages(conversationId: string | undefined) {
  const queryClient = useQueryClient()
  const key = ['agent-chat', conversationId]
  return useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const prev = queryClient.getQueryData<ChatMessage[]>(key) ?? []
      const after = prev.length ? `?after=${encodeURIComponent(prev[prev.length - 1].created_at)}` : ''
      const fresh = await api.get<ChatMessage[]>(`/agent/conversations/${conversationId}/messages${after}`, signal)
      const known = new Set(prev.map((m) => m.id))
      return [...prev, ...fresh.filter((m) => !known.has(m.id))]
    },
    enabled: Boolean(conversationId),
    refetchInterval: (query) => {
      const data = query.state.data
      return data && data.length > 0 && data[data.length - 1].role === 'user' ? CHAT_POLL_MS : false
    },
  })
}

export function useSendChat(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { message: string; conversation_id?: string }) =>
      api.post<ChatPostOut>(`/projects/${projectId}/agent/chat`, body),
    onSuccess: (r) => {
      queryClient.setQueryData<ChatMessage[]>(['agent-chat', r.conversation_id], (prev) =>
        prev?.some((m) => m.id === r.message.id) ? prev : [...(prev ?? []), r.message],
      )
      void queryClient.invalidateQueries({ queryKey: ['agent', projectId, 'conversations'] })
    },
  })
}
