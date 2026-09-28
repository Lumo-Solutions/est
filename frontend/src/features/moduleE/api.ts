import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  BoqRevisionOut,
  ContractOut,
  ContractRevisionOut,
  ContractVariationOut,
  ExclusionRegisterEntryOut,
  OutturnCostObservationOut,
} from '../../types/api'

// All read-only, any authenticated role server-side (app/api/v1/routes/module_e.py
// uses CurrentUser throughout) -- no role gating needed on this page.

export function useContracts(projectId: string | undefined) {
  return useQuery({
    queryKey: ['module-e', projectId, 'contracts'],
    queryFn: ({ signal }) => api.get<ContractOut[]>(`/projects/${projectId}/contracts`, signal),
    enabled: Boolean(projectId),
  })
}

export function useContractRevisions(contractId: string | undefined) {
  return useQuery({
    queryKey: ['module-e', 'contracts', contractId, 'revisions'],
    queryFn: ({ signal }) => api.get<ContractRevisionOut[]>(`/contracts/${contractId}/revisions`, signal),
    enabled: Boolean(contractId),
  })
}

export function useContractVariations(contractId: string | undefined) {
  return useQuery({
    queryKey: ['module-e', 'contracts', contractId, 'variations'],
    queryFn: ({ signal }) => api.get<ContractVariationOut[]>(`/contracts/${contractId}/variations`, signal),
    enabled: Boolean(contractId),
  })
}

export function useBoqRevisions(projectId: string | undefined) {
  return useQuery({
    queryKey: ['module-e', projectId, 'boq-revisions'],
    queryFn: ({ signal }) => api.get<BoqRevisionOut[]>(`/projects/${projectId}/boq-revisions`, signal),
    enabled: Boolean(projectId),
  })
}

export function useExclusionRegister(projectId: string | undefined, status?: string) {
  return useQuery({
    queryKey: ['module-e', projectId, 'exclusion-register', status],
    queryFn: ({ signal }) =>
      api.get<ExclusionRegisterEntryOut[]>(
        `/projects/${projectId}/exclusion-register${status ? `?status=${status}` : ''}`,
        signal,
      ),
    enabled: Boolean(projectId),
  })
}

export function useOutturnCostObservations(projectId: string | undefined) {
  return useQuery({
    queryKey: ['module-e', projectId, 'outturn-cost-observations'],
    queryFn: ({ signal }) =>
      api.get<OutturnCostObservationOut[]>(`/projects/${projectId}/outturn-cost-observations`, signal),
    enabled: Boolean(projectId),
  })
}
