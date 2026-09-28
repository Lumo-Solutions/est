import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { CostItemCreate, CostItemOut, CostItemRateOut, Page, RecordRateRequest } from '../../types/api'

export function useCostItems(params: { search?: string; isActive?: boolean; limit?: number; offset?: number } = {}) {
  const { search, isActive, limit = 50, offset = 0 } = params
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (search) query.set('search', search)
  if (isActive !== undefined) query.set('is_active', String(isActive))
  return useQuery({
    queryKey: ['cost-items', search, isActive, limit, offset],
    queryFn: ({ signal }) => api.get<Page<CostItemOut>>(`/cost-items?${query}`, signal),
  })
}

export function useCostItem(costItemId: string | undefined) {
  return useQuery({
    queryKey: ['cost-items', costItemId],
    queryFn: ({ signal }) => api.get<CostItemOut>(`/cost-items/${costItemId}`, signal),
    enabled: Boolean(costItemId),
  })
}

export function useCreateCostItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CostItemCreate) => api.post<CostItemOut>('/cost-items', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cost-items'] }),
  })
}

export function useCostItemRateAsOf(costItemId: string | undefined, validOn: string) {
  // A 404 here just means "no rate valid on this date" (e.g. before the
  // item's first-ever rate) -- a normal, expected empty state, not a
  // transient failure. The global QueryClient's retry policy (Phase 2,
  // UI-P2-002) already skips retrying any 4xx, so no per-query override
  // is needed here.
  return useQuery({
    queryKey: ['cost-items', costItemId, 'rate', validOn],
    queryFn: ({ signal }) => api.get<CostItemRateOut>(`/cost-items/${costItemId}/rate?valid_on=${validOn}`, signal),
    enabled: Boolean(costItemId),
  })
}

export function useRecordRate(costItemId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: RecordRateRequest) => api.post<CostItemRateOut>(`/cost-items/${costItemId}/rates`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cost-items', costItemId] }),
  })
}
