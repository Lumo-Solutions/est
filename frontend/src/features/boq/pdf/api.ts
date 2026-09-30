import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../lib/api'
import type {
  BoqPdfCommitOut,
  BoqPdfExtractionDetail,
  BoqPdfExtractionOut,
  BoqPdfFileUrlOut,
  BoqPdfRowIn,
} from '../../../types/api'

export const PDF_POLL_MS = 1500

const detailKey = (id: string | null | undefined) => ['boq-pdf-extraction', id]

export function useBoqPdfExtraction(id: string | null | undefined) {
  return useQuery({
    queryKey: detailKey(id),
    queryFn: ({ signal }) => api.get<BoqPdfExtractionDetail>(`/boq-pdf-extractions/${id}`, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? PDF_POLL_MS : false
    },
  })
}

export function useBoqPdfExtractions(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'boq-pdf-extractions'],
    queryFn: ({ signal }) => api.get<BoqPdfExtractionOut[]>(`/projects/${projectId}/boq-pdf-extractions`, signal),
    enabled: Boolean(projectId),
  })
}

export interface StartPdfExtractionInput {
  file?: File | null
  documentId?: string | null
  useAi: boolean
}

export function useStartBoqPdfExtraction(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, documentId, useAi }: StartPdfExtractionInput) => {
      const formData = new FormData()
      if (file) formData.append('file', file)
      else if (documentId) formData.append('document_id', documentId)
      formData.append('use_ai', useAi ? 'true' : 'false')
      return api.post<BoqPdfExtractionOut>(`/projects/${projectId}/boq-pdf-extractions`, formData)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-pdf-extractions'] }),
  })
}

export function useSaveBoqPdfRows(id: string | null | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rows: BoqPdfRowIn[]) => api.put<BoqPdfExtractionDetail>(`/boq-pdf-extractions/${id}/rows`, { rows }),
    onSuccess: (detail) => queryClient.setQueryData(detailKey(id), detail),
  })
}

export function useCommitBoqPdfExtraction(projectId: string | undefined, id: string | null | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BoqPdfCommitOut>(`/boq-pdf-extractions/${id}/commit`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'boq-items'] })
      queryClient.invalidateQueries({ queryKey: detailKey(id) })
    },
  })
}

export function useRetryBoqPdfExtraction(id: string | null | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BoqPdfExtractionOut>(`/boq-pdf-extractions/${id}/retry`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: detailKey(id) }),
  })
}

/** Opens the source PDF at a page in a new tab via a short-lived link. */
export async function openBoqPdfSource(id: string, page: number): Promise<void> {
  const { url } = await api.get<BoqPdfFileUrlOut>(`/boq-pdf-extractions/${id}/file-url`)
  window.open(`${url}#page=${page}`, '_blank', 'noopener')
}
