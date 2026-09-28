import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  AuthorityOut,
  CertificateTypeOut,
  PrequalificationDecision,
  VendorCertificateCreate,
  VendorCertificateOut,
  VendorPrequalificationOut,
} from '../../types/api'

export function useAuthorities() {
  return useQuery({
    queryKey: ['authorities'],
    queryFn: ({ signal }) => api.get<AuthorityOut[]>('/authorities', signal),
  })
}

export function useCertificateTypes() {
  return useQuery({
    queryKey: ['certificate-types'],
    queryFn: ({ signal }) => api.get<CertificateTypeOut[]>('/certificate-types', signal),
  })
}

export function useVendorCertificates(vendorId: string | undefined) {
  return useQuery({
    queryKey: ['vendors', vendorId, 'certificates'],
    queryFn: ({ signal }) => api.get<VendorCertificateOut[]>(`/vendors/${vendorId}/certificates`, signal),
    enabled: Boolean(vendorId),
  })
}

export function useAddCertificate(vendorId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: VendorCertificateCreate) => api.post<VendorCertificateOut>('/vendor-certificates', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendors', vendorId, 'certificates'] }),
  })
}

export function useVerifyCertificate(vendorId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (certificateId: string) =>
      api.post<VendorCertificateOut>(`/vendor-certificates/${certificateId}/verify`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendors', vendorId, 'certificates'] }),
  })
}

export function useVendorPrequalification(vendorId: string | undefined, asOf: string) {
  return useQuery({
    queryKey: ['vendors', vendorId, 'prequalification', asOf],
    queryFn: ({ signal }) =>
      api.get<VendorPrequalificationOut>(`/vendors/${vendorId}/prequalification?as_of=${asOf}`, signal),
    enabled: Boolean(vendorId),
    retry: false,
  })
}

export function useDecidePrequalification(vendorId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: PrequalificationDecision) =>
      api.post<VendorPrequalificationOut>(`/vendors/${vendorId}/prequalification`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendors', vendorId, 'prequalification'] }),
  })
}
