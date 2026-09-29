import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useUsers } from '../users/api'
import type { ApprovalDecision, ApprovalInboxOut, ApprovalRequestOut } from '../../types/api'

export function useApprovalsInbox() {
  return useQuery({
    queryKey: ['approvals', 'inbox'],
    queryFn: ({ signal }) => api.get<ApprovalInboxOut>('/approvals/inbox', signal),
  })
}

export function useApproval(requestId: string | undefined) {
  return useQuery({
    queryKey: ['approvals', 'detail', requestId],
    queryFn: ({ signal }) => api.get<ApprovalRequestOut>(`/approvals/${requestId}`, signal),
    enabled: !!requestId,
  })
}

export function useDecideApproval(requestId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ApprovalDecision) => api.post<ApprovalRequestOut>(`/approvals/${requestId}/decide`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approvals'] }),
  })
}

// Submitter display name. The approvals API only knows the name when the
// local user shadow row has one; the Keycloak-backed /users directory (open
// to every approver role) is the reliable source, so prefer it.
export function useSubmitterName() {
  const { data: users } = useUsers()
  return (r: Pick<ApprovalRequestOut, 'requested_by' | 'requested_by_name'>): string =>
    users?.find((u) => u.id === r.requested_by)?.username ?? r.requested_by_name ?? 'unknown user'
}
