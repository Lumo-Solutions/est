import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  DuplicateCandidateOut,
  DuplicateCheckResult,
  DuplicateResolveRequest,
  Page,
  VendorCreate,
  VendorOut,
} from '../../types/api'

export function useVendors(params: { status?: string; limit?: number; offset?: number } = {}) {
  const { status, limit = 50, offset = 0 } = params
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) query.set('status', status)
  return useQuery({
    queryKey: ['vendors', status, limit, offset],
    queryFn: ({ signal }) => api.get<Page<VendorOut>>(`/vendors?${query}`, signal),
  })
}

export function useVendor(vendorId: string | undefined) {
  return useQuery({
    queryKey: ['vendors', vendorId],
    queryFn: ({ signal }) => api.get<VendorOut>(`/vendors/${vendorId}`, signal),
    enabled: Boolean(vendorId),
  })
}

export function useCreateVendor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ data, force }: { data: VendorCreate; force?: boolean }) =>
      api.post<VendorOut>(`/vendors${force ? '?force=true' : ''}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendors'] }),
  })
}

export function useCheckDuplicates() {
  return useMutation({
    mutationFn: (data: VendorCreate) => api.post<DuplicateCheckResult>('/vendors:check-duplicates', data),
  })
}

export function useDuplicateCandidates(status = 'open') {
  return useQuery({
    queryKey: ['vendor-duplicates', status],
    queryFn: ({ signal }) => api.get<DuplicateCandidateOut[]>(`/vendors/duplicates/list?status=${status}`, signal),
  })
}

export function useResolveDuplicate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ candidateId, data }: { candidateId: string; data: DuplicateResolveRequest }) =>
      api.post<DuplicateCandidateOut>(`/vendors/duplicates/${candidateId}/resolve`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendor-duplicates'] }),
  })
}

export function useScanDuplicates(vendorId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<DuplicateCandidateOut[]>(`/vendors/${vendorId}/duplicate-scan`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendor-duplicates'] }),
  })
}

export function useVendorServiceRegions(vendorId: string | undefined) {
  return useQuery({
    queryKey: ['vendors', vendorId, 'service-regions'],
    queryFn: ({ signal }) => api.get<string[]>(`/vendors/${vendorId}/service-regions`, signal),
    enabled: Boolean(vendorId),
  })
}
