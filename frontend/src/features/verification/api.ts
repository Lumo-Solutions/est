import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  AnnotationSummaryOut,
  VerificationClass,
  VerificationEvidenceOut,
  VerificationLinesPage,
  VerificationMappingRequest,
  VerificationMappingResult,
  VerificationRunOut,
} from '../../types/api'

export const PAGE_SIZE = 200
export const POLL_MS = 1500

export interface LineFilters {
  vclass: VerificationClass[]
  trade: string
  band: '' | 'low' | 'medium' | 'high'
  q: string
  offset: number
}

export const EMPTY_FILTERS: LineFilters = { vclass: [], trade: '', band: '', q: '', offset: 0 }

// Confidence bands: low < 0.5, medium 0.5 - 0.8, high >= 0.8.
export function bandRange(band: LineFilters['band']): { min?: number; max?: number } {
  if (band === 'low') return { max: 0.4999 }
  if (band === 'medium') return { min: 0.5, max: 0.7999 }
  if (band === 'high') return { min: 0.8 }
  return {}
}

export function isActive(run: VerificationRunOut | undefined) {
  return run?.status === 'queued' || run?.status === 'running'
}

export function useVerificationRuns(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'verification-runs'],
    queryFn: ({ signal }) => api.get<VerificationRunOut[]>(`/projects/${projectId}/verification-runs`, signal),
    enabled: Boolean(projectId),
  })
}

export function useVerificationRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['verification-runs', runId],
    queryFn: ({ signal }) => api.get<VerificationRunOut>(`/verification-runs/${runId}`, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => (isActive(query.state.data) ? POLL_MS : false),
  })
}

export function useStartVerification(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (useAi: boolean) =>
      api.post<VerificationRunOut>(`/projects/${projectId}/verification-runs`, { use_ai: useAi }),
    onSuccess: (run) => {
      queryClient.setQueryData(['verification-runs', run.id], run)
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'verification-runs'] })
    },
  })
}

export function useRetryVerification(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => api.post<VerificationRunOut>(`/verification-runs/${runId}/retry`),
    onSuccess: (run) => {
      queryClient.setQueryData(['verification-runs', run.id], run)
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'verification-runs'] })
    },
  })
}

export function useVerificationLines(runId: string | undefined, filters: LineFilters, enabled = true) {
  const params = new URLSearchParams()
  if (filters.vclass.length === 1) params.set('vclass', filters.vclass[0])
  if (filters.trade) params.set('trade', filters.trade)
  const { min, max } = bandRange(filters.band)
  if (min !== undefined) params.set('min_confidence', String(min))
  if (max !== undefined) params.set('max_confidence', String(max))
  if (filters.q.trim()) params.set('q', filters.q.trim())
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(filters.offset))
  const query = params.toString()
  return useQuery({
    queryKey: ['verification-runs', runId, 'lines', query],
    queryFn: ({ signal }) =>
      api.get<VerificationLinesPage>(`/verification-runs/${runId}/lines?${query}`, signal),
    enabled: Boolean(runId) && enabled,
    placeholderData: keepPreviousData,
  })
}

export function useLineMapping(runId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ lineId, body }: { lineId: string; body: VerificationMappingRequest }) =>
      api.post<VerificationMappingResult>(`/verification-runs/${runId}/lines/${lineId}/mapping`, body),
    onSuccess: ({ line, run }) => {
      queryClient.setQueryData(['verification-runs', runId], run)
      // Update the line in place in every cached page (filters may differ).
      queryClient.setQueriesData<VerificationLinesPage>(
        { queryKey: ['verification-runs', runId, 'lines'] },
        (page) => (page ? { ...page, items: page.items.map((l) => (l.id === line.id ? line : l)) } : page),
      )
    },
  })
}

export function useVerificationEvidence(projectId: string | undefined, q: string, kind: string, enabled: boolean) {
  const params = new URLSearchParams()
  if (q.trim()) params.set('q', q.trim())
  if (kind) params.set('kind', kind)
  params.set('limit', '25')
  return useQuery({
    queryKey: ['projects', projectId, 'verification-evidence', params.toString()],
    queryFn: ({ signal }) =>
      api.get<{ items: VerificationEvidenceOut[] }>(`/projects/${projectId}/verification-evidence?${params}`, signal),
    enabled: Boolean(projectId) && enabled,
  })
}

export function useAnnotationSummary(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawing-annotations', 'summary'],
    queryFn: ({ signal }) =>
      api.get<AnnotationSummaryOut>(`/projects/${projectId}/drawing-annotations/summary`, signal),
    enabled: Boolean(projectId),
  })
}

export function useReadAnnotations(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.post<{ queued_sheets: number }>(`/projects/${projectId}/drawing-annotations:read`, {}),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawing-annotations'] }),
  })
}

// Exports are GET downloads (the shared downloadFile helper is POST-only).
export async function downloadVerificationExport(runId: string, ext: 'xlsx' | 'pdf'): Promise<void> {
  const response = await fetch(`/api/v1/verification-runs/${runId}/export.${ext}`, { credentials: 'same-origin' })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const problem = await response.json()
      detail = problem.detail || problem.title || detail
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `Export failed (${response.status})`)
  }
  const blob = await response.blob()
  const match = response.headers.get('content-disposition')?.match(/filename="?([^"]+)"?/)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = match ? match[1] : `verification.${ext}`
  link.click()
  URL.revokeObjectURL(url)
}

export function useVerificationExport(runId: string | undefined) {
  return useMutation({
    mutationFn: (ext: 'xlsx' | 'pdf') => downloadVerificationExport(runId as string, ext),
  })
}
