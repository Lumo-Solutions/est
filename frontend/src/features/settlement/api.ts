import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, downloadFile } from '../../lib/api'
import type {
  ApprovalDecision,
  BidSettlementLineItemOut,
  BidSettlementOut,
  BidSettlementScenarioOut,
  BidSettlementTradeOverrideOut,
  ExportRequest,
  FidelityReportOut,
  FxRateSet,
  LineCostUpdate,
  OutcomeRequest,
  ScenarioCreate,
  SettlementDefaultsUpdate,
  SettlementReasonCodeOut,
  SimulateRequest,
  SimulateResult,
  TradeOverrideUpdate,
} from '../../types/api'

export function useSettlements(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'bid-settlements'],
    queryFn: ({ signal }) => api.get<BidSettlementOut[]>(`/projects/${projectId}/bid-settlements`, signal),
    enabled: Boolean(projectId),
  })
}

export function useBuildSettlementDraft(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BidSettlementOut>(`/projects/${projectId}/bid-settlements`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'bid-settlements'] }),
  })
}

export function useSettlement(settlementId: string | undefined) {
  return useQuery({
    queryKey: ['bid-settlements', settlementId],
    queryFn: ({ signal }) => api.get<BidSettlementOut>(`/bid-settlements/${settlementId}`, signal),
    enabled: Boolean(settlementId),
  })
}

function invalidateSettlement(queryClient: ReturnType<typeof useQueryClient>, projectId: string | undefined, settlementId: string | undefined) {
  queryClient.invalidateQueries({ queryKey: ['bid-settlements', settlementId] })
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'bid-settlements'] })
}

export function useUpdateSettlementDefaults(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: SettlementDefaultsUpdate) => api.patch<BidSettlementOut>(`/bid-settlements/${settlementId}/defaults`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useRefreshQuantities(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BidSettlementOut>(`/bid-settlements/${settlementId}/refresh-quantities`),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useSimulate(settlementId: string | undefined) {
  return useMutation({
    mutationFn: (data: SimulateRequest) => api.post<SimulateResult>(`/bid-settlements/${settlementId}/simulate`, data),
  })
}

export function useScenarios(settlementId: string | undefined) {
  return useQuery({
    queryKey: ['bid-settlements', settlementId, 'scenarios'],
    queryFn: ({ signal }) => api.get<BidSettlementScenarioOut[]>(`/bid-settlements/${settlementId}/scenarios`, signal),
    enabled: Boolean(settlementId),
  })
}

export function useSaveScenario(settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ScenarioCreate) =>
      api.post<BidSettlementScenarioOut>(`/bid-settlements/${settlementId}/scenarios`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bid-settlements', settlementId, 'scenarios'] }),
  })
}

export function useDeleteScenario(settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (scenarioId: string) => api.delete<void>(`/bid-settlements/${settlementId}/scenarios/${scenarioId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bid-settlements', settlementId, 'scenarios'] }),
  })
}

export function useSetTradeOverride(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ tradeNodeId, data }: { tradeNodeId: string; data: TradeOverrideUpdate }) =>
      api.put<BidSettlementTradeOverrideOut>(`/bid-settlements/${settlementId}/trade-overrides/${tradeNodeId}`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useUpdateSettlementLine(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ lineId, data }: { lineId: string; data: LineCostUpdate }) =>
      api.patch<BidSettlementLineItemOut>(`/bid-settlements/${settlementId}/lines/${lineId}`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useSetLineFxRate(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ lineId, data }: { lineId: string; data: FxRateSet }) =>
      api.post<BidSettlementLineItemOut>(`/bid-settlements/${settlementId}/lines/${lineId}/fx-rate`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useSubmitSettlement(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BidSettlementOut>(`/bid-settlements/${settlementId}/submit`),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useDecideSettlement(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ApprovalDecision) => api.post<BidSettlementOut>(`/bid-settlements/${settlementId}/decide`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useRecordOutcome(projectId: string | undefined, settlementId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: OutcomeRequest) => api.post<BidSettlementOut>(`/bid-settlements/${settlementId}/outcome`, data),
    onSuccess: () => invalidateSettlement(queryClient, projectId, settlementId),
  })
}

export function useReasonCodes() {
  return useQuery({
    queryKey: ['settlement-reason-codes'],
    queryFn: ({ signal }) => api.get<SettlementReasonCodeOut[]>('/settlement-reason-codes', signal),
  })
}

export function useExportSettlement(settlementId: string | undefined) {
  return useMutation({
    mutationFn: (data: ExportRequest) =>
      downloadFile(`/bid-settlements/${settlementId}/export`, data, 'settlement.xlsx'),
  })
}

export function usePreviewOriginalExport(settlementId: string | undefined) {
  return useMutation({
    mutationFn: () => api.post<FidelityReportOut>(`/bid-settlements/${settlementId}/export-original/preview`),
  })
}

export function useExportOriginalSettlement(settlementId: string | undefined) {
  return useMutation({
    mutationFn: () =>
      downloadFile(`/bid-settlements/${settlementId}/export-original`, { accept_loss: true }, 'settlement-original.xlsx'),
  })
}
