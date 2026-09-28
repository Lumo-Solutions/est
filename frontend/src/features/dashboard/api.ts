import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  ApprovalRequestOut,
  DuplicateCandidateOut,
  ExpiringVendorCertificateOut,
  InboundEmailOut,
} from '../../types/api'

// Phase 3 gap-fill (docs/ui-qa-brief.md): home dashboard "what needs my
// attention" tiles, one hook per existing (or newly added, see
// docs/ui-qa/log.md's Phase 3 section) list endpoint. Each hook is used by
// whichever role sections actually want that tile -- see
// HomeDashboardPage.tsx for which roles see which.

export function usePendingApprovalsForMe() {
  return useQuery({
    queryKey: ['approvals', 'pending-for-me'],
    queryFn: ({ signal }) => api.get<ApprovalRequestOut[]>('/approvals/pending-for-me', signal),
  })
}

export function useQuarantineQueueForDashboard() {
  return useQuery({
    queryKey: ['quotation-inbound-review'],
    queryFn: ({ signal }) => api.get<InboundEmailOut[]>('/quotation-inbound-review', signal),
  })
}

export function useOpenVendorDuplicatesForDashboard() {
  return useQuery({
    queryKey: ['vendors', 'duplicates', 'open'],
    queryFn: ({ signal }) => api.get<DuplicateCandidateOut[]>('/vendors/duplicates/list?status=open', signal),
  })
}

export function useExpiringCertificatesForDashboard(days = 30) {
  return useQuery({
    queryKey: ['vendor-certificates', 'expiring', days],
    queryFn: ({ signal }) =>
      api.get<ExpiringVendorCertificateOut[]>(`/vendor-certificates/expiring?days=${days}`, signal),
  })
}
