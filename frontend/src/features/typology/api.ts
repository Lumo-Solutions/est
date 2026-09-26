import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  ConfirmClusterRequest,
  TypologyClusterInstanceOut,
  TypologyClusterOut,
  TypologyRollupOut,
  TypologyVariantDeltaOut,
} from '../../types/api'

export function useTypologyClusters(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'typology-clusters'],
    queryFn: ({ signal }) => api.get<TypologyClusterOut[]>(`/projects/${projectId}/typology-clusters`, signal),
    enabled: Boolean(projectId),
  })
}

export function useDetectTypologyClusters(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<TypologyClusterOut[]>(`/projects/${projectId}/typology-clusters/detect`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'typology-clusters'] }),
  })
}

export function useTypologyClusterInstances(clusterId: string | undefined) {
  return useQuery({
    queryKey: ['typology-clusters', clusterId, 'instances'],
    queryFn: ({ signal }) =>
      api.get<TypologyClusterInstanceOut[]>(`/typology-clusters/${clusterId}/instances`, signal),
    enabled: Boolean(clusterId),
  })
}

export function useTypologyVariantDeltas(clusterId: string | undefined) {
  return useQuery({
    queryKey: ['typology-clusters', clusterId, 'deltas'],
    queryFn: ({ signal }) => api.get<TypologyVariantDeltaOut[]>(`/typology-clusters/${clusterId}/deltas`, signal),
    enabled: Boolean(clusterId),
  })
}

export function useTypologyRollup(clusterId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['typology-clusters', clusterId, 'rollup'],
    queryFn: ({ signal }) => api.get<TypologyRollupOut>(`/typology-clusters/${clusterId}/rollup`, signal),
    enabled: Boolean(clusterId) && enabled,
  })
}

export function useConfirmTypologyCluster(projectId: string | undefined, clusterId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ConfirmClusterRequest) =>
      api.post<TypologyClusterOut>(`/typology-clusters/${clusterId}/confirm`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'typology-clusters'] }),
  })
}

export function useRejectTypologyCluster(projectId: string | undefined, clusterId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<TypologyClusterOut>(`/typology-clusters/${clusterId}/reject`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'typology-clusters'] }),
  })
}
