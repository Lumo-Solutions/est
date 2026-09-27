import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  ApprovalPolicyCreate,
  ApprovalPolicyOut,
  ApprovalPolicySetActive,
  BoqToleranceOut,
  BoqToleranceSet,
  DrawingLayerTradeMappingIn,
  DrawingLayerTradeMappingOut,
  Page,
  ReasonCodeCreate,
  ReasonCodeUpdate,
  SettlementReasonCodeOut,
  TradeNodeCreate,
  TradeNodeOut,
  TradeNodeUpdate,
  VendorOut,
} from '../../types/api'

// --- taxonomy ---

export function useTaxonomyNodes(activeOnly = true) {
  return useQuery({
    queryKey: ['taxonomy', { activeOnly }],
    queryFn: ({ signal }) => api.get<TradeNodeOut[]>(`/taxonomy?active_only=${activeOnly}`, signal),
  })
}

export function useCreateTaxonomyNode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: TradeNodeCreate) => api.post<TradeNodeOut>('/taxonomy', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['taxonomy'] }),
  })
}

export function useUpdateTaxonomyNode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ nodeId, data }: { nodeId: string; data: TradeNodeUpdate }) =>
      api.patch<TradeNodeOut>(`/taxonomy/${nodeId}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['taxonomy'] }),
  })
}

export function useMoveTaxonomyNode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ nodeId, newParentId }: { nodeId: string; newParentId: string | null }) =>
      api.post<TradeNodeOut>(`/taxonomy/${nodeId}/move`, { new_parent_id: newParentId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['taxonomy'] }),
  })
}

// --- BOQ tolerances (per project) ---

export function useBoqTolerances(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'boq-tolerances'],
    queryFn: ({ signal }) => api.get<BoqToleranceOut[]>(`/projects/${projectId}/boq-tolerances`, signal),
    enabled: Boolean(projectId),
  })
}

export function useSetBoqTolerance(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: BoqToleranceSet) => api.put<BoqToleranceOut>(`/projects/${projectId}/boq-tolerances`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-tolerances'] }),
  })
}

// --- drawing layer-to-trade mapping (per project) ---

export function useLayerTradeMappings(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawing-layer-trade-mappings'],
    queryFn: ({ signal }) =>
      api.get<DrawingLayerTradeMappingOut[]>(`/projects/${projectId}/drawing-layer-trade-mappings`, signal),
    enabled: Boolean(projectId),
  })
}

export function useReplaceLayerTradeMappings(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: DrawingLayerTradeMappingIn[]) =>
      api.put<DrawingLayerTradeMappingOut[]>(`/projects/${projectId}/drawing-layer-trade-mappings`, data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawing-layer-trade-mappings'] }),
  })
}

// --- vendors + service regions ---

export function useVendorsPage(limit = 50) {
  return useQuery({
    queryKey: ['vendors', { limit }],
    queryFn: ({ signal }) => api.get<Page<VendorOut>>(`/vendors?limit=${limit}`, signal),
  })
}

export function useVendorServiceRegions(vendorId: string | undefined) {
  return useQuery({
    queryKey: ['vendors', vendorId, 'service-regions'],
    queryFn: ({ signal }) => api.get<string[]>(`/vendors/${vendorId}/service-regions`, signal),
    enabled: Boolean(vendorId),
  })
}

export function useReplaceVendorServiceRegions(vendorId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (emirates: string[]) => api.put<string[]>(`/vendors/${vendorId}/service-regions`, emirates),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendors', vendorId, 'service-regions'] }),
  })
}

// --- approval policies ---

export function useApprovalPolicies() {
  return useQuery({
    queryKey: ['approval-policies'],
    queryFn: ({ signal }) => api.get<ApprovalPolicyOut[]>('/approvals/policies', signal),
  })
}

export function useCreateApprovalPolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ApprovalPolicyCreate) => api.post<ApprovalPolicyOut>('/approvals/policies', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approval-policies'] }),
  })
}

export function useSetApprovalPolicyActive() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ policyId, data }: { policyId: string; data: ApprovalPolicySetActive }) =>
      api.patch<ApprovalPolicyOut>(`/approvals/policies/${policyId}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approval-policies'] }),
  })
}

// --- reason codes (admin, includes inactive) ---

export function useAdminReasonCodes() {
  return useQuery({
    queryKey: ['settlement-reason-codes', { includeInactive: true }],
    queryFn: ({ signal }) => api.get<SettlementReasonCodeOut[]>('/settlement-reason-codes?include_inactive=true', signal),
  })
}

export function useCreateReasonCode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ReasonCodeCreate) => api.post<SettlementReasonCodeOut>('/settlement-reason-codes', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settlement-reason-codes'] }),
  })
}

export function useUpdateReasonCode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ReasonCodeUpdate }) =>
      api.patch<SettlementReasonCodeOut>(`/settlement-reason-codes/${id}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settlement-reason-codes'] }),
  })
}
