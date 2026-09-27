import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { AuditEventOut, ChainVerifyResult } from '../../types/api'

export function useAuditEvents(filters: { entityType?: string; entityId?: string; limit?: number }) {
  const params = new URLSearchParams()
  if (filters.entityType) params.set('entity_type', filters.entityType)
  if (filters.entityId) params.set('entity_id', filters.entityId)
  params.set('limit', String(filters.limit ?? 100))
  return useQuery({
    queryKey: ['audit-events', filters],
    queryFn: ({ signal }) => api.get<AuditEventOut[]>(`/audit/events?${params.toString()}`, signal),
  })
}

export function useVerifyAuditChain() {
  return useMutation({
    mutationFn: ({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) =>
      api.get<ChainVerifyResult>(`/audit/verify?date_from=${dateFrom}&date_to=${dateTo}`),
  })
}
