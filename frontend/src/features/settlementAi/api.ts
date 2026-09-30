import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  BulkAcceptResult,
  CostProposal,
  CostProposalDecision,
  CostProposalPage,
  SettlementAiRun,
} from '../../types/api'

export interface ProposalFilters {
  status?: string
  flagged?: boolean
  noSource?: boolean
  minConfidence?: number
  maxConfidence?: number
  limit?: number
  offset?: number
}

export function proposalsQuery(filters: ProposalFilters): string {
  const p = new URLSearchParams()
  if (filters.status) p.set('status', filters.status)
  if (filters.flagged) p.set('flagged', 'true')
  if (filters.noSource) p.set('no_source', 'true')
  if (filters.minConfidence != null) p.set('min_confidence', String(filters.minConfidence))
  if (filters.maxConfidence != null) p.set('max_confidence', String(filters.maxConfidence))
  p.set('limit', String(filters.limit ?? 50))
  p.set('offset', String(filters.offset ?? 0))
  return p.toString()
}

export const isRunActive = (run: SettlementAiRun | undefined) => run?.status === 'queued' || run?.status === 'running'

export function useSettlementAiRuns(settlementId: string | undefined) {
  return useQuery({
    queryKey: ['settlement-ai', settlementId, 'runs'],
    queryFn: ({ signal }) => api.get<SettlementAiRun[]>(`/bid-settlements/${settlementId}/ai/runs`, signal),
    enabled: Boolean(settlementId),
  })
}

// Polls every 1.5 s while the run is queued/running, then stops.
export function useSettlementAiRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['settlement-ai-runs', runId],
    queryFn: ({ signal }) => api.get<SettlementAiRun>(`/settlement-ai-runs/${runId}`, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => (isRunActive(query.state.data) ? 1500 : false),
  })
}

export function useStartAiRun(settlementId: string | undefined, kind: 'costs' | 'markup') {
  const queryClient = useQueryClient()
  const path = kind === 'costs' ? 'cost-proposals' : 'markup-advice'
  return useMutation({
    mutationFn: (useAi: boolean) =>
      api.post<SettlementAiRun>(`/bid-settlements/${settlementId}/ai/${path}`, { use_ai: useAi }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settlement-ai', settlementId, 'runs'] }),
  })
}

export function useCostProposals(settlementId: string | undefined, filters: ProposalFilters) {
  return useQuery({
    queryKey: ['settlement-ai', settlementId, 'proposals', filters],
    queryFn: ({ signal }) =>
      api.get<CostProposalPage>(`/bid-settlements/${settlementId}/ai/proposals?${proposalsQuery(filters)}`, signal),
    enabled: Boolean(settlementId),
  })
}

function useInvalidateAfterCost(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ['settlement-ai', settlementId, 'proposals'] })
    // A decision applies a cost to the settlement line through the normal rules.
    queryClient.invalidateQueries({ queryKey: ['bid-settlements', settlementId] })
    queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'bid-settlements'] })
  }
}

export function useDecideProposal(projectId: string | undefined, settlementId: string | undefined) {
  const invalidate = useInvalidateAfterCost(projectId, settlementId)
  return useMutation({
    mutationFn: ({ proposalId, data }: { proposalId: string; data: CostProposalDecision }) =>
      api.post<CostProposal>(`/settlement-ai-proposals/${proposalId}/decision`, data),
    onSuccess: invalidate,
  })
}

export function useBulkAccept(projectId: string | undefined, settlementId: string | undefined) {
  const invalidate = useInvalidateAfterCost(projectId, settlementId)
  return useMutation({
    mutationFn: (minConfidence: number) =>
      api.post<BulkAcceptResult>(`/bid-settlements/${settlementId}/ai/proposals:bulk-accept`, {
        min_confidence: minConfidence,
      }),
    onSuccess: invalidate,
  })
}

// The run a panel shows: the one just started, else the newest of its kind.
export function useTrackedRun(settlementId: string | undefined, kind: 'costs' | 'markup') {
  const [startedId, setStartedId] = useState<string | undefined>()
  const runs = useSettlementAiRuns(settlementId)
  const start = useStartAiRun(settlementId, kind)
  const latestId = runs.data?.find((r) => r.kind === kind)?.id
  const runId = startedId ?? latestId
  const runQuery = useSettlementAiRun(runId)
  return {
    run: runQuery.data,
    start: (useAi: boolean) => start.mutate(useAi, { onSuccess: (r) => setStartedId(r.id) }),
    starting: start.isPending,
    startError: start.isError ? start.error.message : null,
  }
}
