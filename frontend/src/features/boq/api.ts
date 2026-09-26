import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  BoqImportColumnMappingIn,
  BoqImportCommitOut,
  BoqImportPreviewOut,
  BoqLineItemOut,
  FeedbackCreate,
  LinkedMeasurementOut,
  SuggestionOut,
} from '../../types/api'

export function useBoqItems(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'boq-items'],
    queryFn: ({ signal }) => api.get<BoqLineItemOut[]>(`/projects/${projectId}/boq-items`, signal),
    enabled: Boolean(projectId),
  })
}

export function useUnlinkedMeasurements(
  projectId: string | undefined,
  filters: { drawingId?: string; tradeNodeId?: string } = {},
) {
  const params = new URLSearchParams()
  if (filters.drawingId) params.set('drawing_id', filters.drawingId)
  if (filters.tradeNodeId) params.set('trade_node_id', filters.tradeNodeId)
  const query = params.toString()
  return useQuery({
    queryKey: ['projects', projectId, 'measurements-unlinked', filters],
    queryFn: ({ signal }) =>
      api.get<LinkedMeasurementOut[]>(`/projects/${projectId}/measurements:unlinked?${query}`, signal),
    enabled: Boolean(projectId),
  })
}

export function useMeasurementLinks(itemId: string | undefined) {
  return useQuery({
    queryKey: ['boq-items', itemId, 'measurements'],
    queryFn: ({ signal }) => api.get<LinkedMeasurementOut[]>(`/boq-items/${itemId}/measurements`, signal),
    enabled: Boolean(itemId),
  })
}

function invalidateItem(queryClient: ReturnType<typeof useQueryClient>, projectId: string | undefined, itemId: string | undefined) {
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-items'] })
  queryClient.invalidateQueries({ queryKey: ['boq-items', itemId, 'measurements'] })
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'measurements-unlinked'] })
}

export function useLinkMeasurement(projectId: string | undefined, itemId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (measurementId: string) =>
      api.post<BoqLineItemOut>(`/boq-items/${itemId}/measurements`, { measurement_id: measurementId }),
    onSuccess: () => invalidateItem(queryClient, projectId, itemId),
  })
}

export function useUnlinkMeasurement(projectId: string | undefined, itemId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (measurementId: string) => api.delete(`/boq-items/${itemId}/measurements/${measurementId}`),
    onSuccess: () => invalidateItem(queryClient, projectId, itemId),
  })
}

export function useReconcileBoqItem(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => api.post<BoqLineItemOut>(`/boq-items/${itemId}/reconcile`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-items'] }),
  })
}

export function useMeasurementSuggestions(itemId: string | undefined) {
  return useQuery({
    queryKey: ['boq-line-items', itemId, 'measurement-suggestions'],
    queryFn: ({ signal }) =>
      api.get<SuggestionOut[]>(`/boq-line-items/${itemId}/measurement-suggestions?top_k=5`, signal),
    enabled: Boolean(itemId),
  })
}

export function useRecordSemanticFeedback() {
  return useMutation({
    mutationFn: (data: FeedbackCreate) => api.post(`/semantic-matching/feedback`, data),
  })
}

export function useBoqImportPreview(projectId: string | undefined) {
  return useMutation({
    mutationFn: ({ file, mapping }: { file: File; mapping: BoqImportColumnMappingIn }) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('mapping', JSON.stringify(mapping))
      return api.post<BoqImportPreviewOut>(`/projects/${projectId}/boq-items:import-preview`, formData)
    },
  })
}

export function useBoqImportCommit(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, mapping }: { file: File; mapping: BoqImportColumnMappingIn }) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('mapping', JSON.stringify(mapping))
      return api.post<BoqImportCommitOut>(`/projects/${projectId}/boq-items:import-commit`, formData)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-items'] }),
  })
}
