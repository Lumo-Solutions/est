import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  BoqLineItemOut,
  MatchedVendorOut,
  ProcurementPackageCreate,
  ProcurementPackageOut,
  RfqCreateRequest,
  RfqOut,
} from '../../types/api'

export function useProcurementPackages(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'procurement-packages'],
    queryFn: ({ signal }) => api.get<ProcurementPackageOut[]>(`/projects/${projectId}/procurement-packages`, signal),
    enabled: Boolean(projectId),
  })
}

export function useCreateProcurementPackage(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProcurementPackageCreate) =>
      api.post<ProcurementPackageOut>(`/projects/${projectId}/procurement-packages`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'procurement-packages'] }),
  })
}

export function usePackageItems(packageId: string | undefined) {
  return useQuery({
    queryKey: ['procurement-packages', packageId, 'items'],
    queryFn: ({ signal }) => api.get<BoqLineItemOut[]>(`/procurement-packages/${packageId}/items`, signal),
    enabled: Boolean(packageId),
  })
}

export function useAddPackageItems(packageId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (boqLineItemIds: string[]) =>
      api.post<BoqLineItemOut[]>(`/procurement-packages/${packageId}/items`, { boq_line_item_ids: boqLineItemIds }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['procurement-packages', packageId, 'items'] }),
  })
}

export function useMatchedVendors(packageId: string | undefined) {
  return useQuery({
    queryKey: ['procurement-packages', packageId, 'matched-vendors'],
    queryFn: ({ signal }) => api.get<MatchedVendorOut[]>(`/procurement-packages/${packageId}/matched-vendors`, signal),
    enabled: Boolean(packageId),
  })
}

export function useRfqs(packageId: string | undefined) {
  return useQuery({
    queryKey: ['procurement-packages', packageId, 'rfqs'],
    queryFn: ({ signal }) => api.get<RfqOut[]>(`/procurement-packages/${packageId}/rfqs`, signal),
    enabled: Boolean(packageId),
  })
}

export function useCreateRfqs(packageId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: RfqCreateRequest) => api.post<RfqOut[]>(`/procurement-packages/${packageId}/rfqs`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['procurement-packages', packageId, 'rfqs'] }),
  })
}

export function useDispatchRfq(packageId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rfqId: string) => api.post<RfqOut>(`/rfqs/${rfqId}/dispatch`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['procurement-packages', packageId, 'rfqs'] }),
  })
}

export function useResendRfq(packageId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ rfqId, reason }: { rfqId: string; reason: string }) =>
      api.post<RfqOut>(`/rfqs/${rfqId}/resend`, { reason }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['procurement-packages', packageId, 'rfqs'] }),
  })
}
