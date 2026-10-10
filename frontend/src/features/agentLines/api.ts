import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { AgentLine, AgentSummary, BulkConfirmResult } from './types'

export function useAgentSummary(settlementId: string | undefined) {
  return useQuery({
    queryKey: ['bid-settlements', settlementId, 'agent-summary'],
    queryFn: ({ signal }) => api.get<AgentSummary>(`/bid-settlements/${settlementId}/agent-summary`, signal),
    enabled: Boolean(settlementId),
  })
}

export function useAgentLines(settlementId: string | undefined) {
  return useQuery({
    queryKey: ['bid-settlements', settlementId, 'agent-lines'],
    queryFn: ({ signal }) => api.get<AgentLine[]>(`/bid-settlements/${settlementId}/agent-lines`, signal),
    enabled: Boolean(settlementId),
  })
}

// ['bid-settlements', id] also covers the settlement detail, so the lines grid follows.
export function useRefreshAgent(settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['bid-settlements', settlementId] })
}

export function useAgentConfirm(settlementId: string | undefined) {
  const refresh = useRefreshAgent(settlementId)
  return useMutation({
    mutationFn: ({ lineId, proposalId }: { lineId: string; proposalId: string }) =>
      api.post<unknown>(`/bid-settlements/${settlementId}/lines/${lineId}/agent-confirm`, { proposal_id: proposalId }),
    // On a 409 the line moved on: reload so the drawer shows the new proposal.
    onSettled: () => refresh(),
  })
}

export function useAgentConfirmBulk(settlementId: string | undefined) {
  const refresh = useRefreshAgent(settlementId)
  return useMutation({
    mutationFn: () => api.post<BulkConfirmResult>(`/bid-settlements/${settlementId}/agent-confirm-bulk`),
    onSettled: () => refresh(),
  })
}
