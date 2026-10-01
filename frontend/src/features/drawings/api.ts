import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  DrawingAnnotationPage,
  DrawingAnnotationSummaryOut,
  DrawingEntityOut,
  DrawingMeasurementOut,
  DrawingOut,
  DrawingMeasureStateOut,
  DrawingSheetOut,
  ManualScaleCalibrationIn,
  MeasureOut,
  MeasureRequest,
  MeasurementOverrideIn,
  MeasurementOverrideOut,
  ReadAnnotationsIn,
  MeasurementSummary,
  ReadAnnotationsOut,
  SheetScaleCalibrationOut,
} from '../../types/api'

export function useDrawings(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawings'],
    queryFn: ({ signal }) => api.get<DrawingOut[]>(`/projects/${projectId}/drawings`, signal),
    enabled: Boolean(projectId),
  })
}

export interface UploadOutcome {
  filename: string
  ok: boolean
  error?: string
}

// One drawing per request (the API takes a single file), sequentially, so a
// bad file never blocks the rest: every file reports its own outcome. A DWG
// goes through the same two calls -- ingest is what starts its conversion.
export function useUploadDrawings(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (files: File[]): Promise<UploadOutcome[]> => {
      const outcomes: UploadOutcome[] = []
      for (const file of files) {
        try {
          const formData = new FormData()
          formData.append('file', file)
          const drawing = await api.post<DrawingOut>(`/projects/${projectId}/drawings`, formData)
          await api.post(`/drawings/${drawing.id}/ingest`)
          outcomes.push({ filename: file.name, ok: true })
        } catch (e) {
          outcomes.push({ filename: file.name, ok: false, error: e instanceof Error ? e.message : 'Upload failed' })
        }
      }
      return outcomes
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawings'] }),
  })
}

// GET /drawings/{id}/download redirects to a presigned S3 URL, so a plain
// link works (same as quotation attachments). `derived` is the DXF a DWG was
// converted to.
export function drawingDownloadHref(drawingId: string, variant: 'original' | 'derived' = 'original'): string {
  return `/api/v1/drawings/${drawingId}/download?variant=${variant}`
}

// "Retry extraction" is just re-triggering ingest -- every task in the
// pipeline is already idempotent-replay-safe (see docs/takeoff-pipeline.md),
// so this resumes from whatever already succeeded rather than starting over.
// Only meaningful (and only shown by the page) once the drawing is no
// longer actively processing, i.e. status is `failed`/`partial`.
export function useRetryIngest(projectId: string | undefined, drawingId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post(`/drawings/${drawingId}/ingest`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId] })
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawings'] })
    },
  })
}

export function useDrawing(drawingId: string | undefined) {
  return useQuery({
    queryKey: ['drawings', drawingId],
    queryFn: ({ signal }) => api.get<DrawingOut>(`/drawings/${drawingId}`, signal),
    enabled: Boolean(drawingId),
    // Polls while extraction is still running so the sheet index picks up
    // "ready"/"failed" without a manual refresh.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (query.state.data?.measurement === 'queued' || query.state.data?.measurement === 'measuring') return 3000
      return status && ['queued', 'converting', 'indexing', 'extracting', 'embedding'].includes(status) ? 3000 : false
    },
  })
}

const EXTRACTING = ['queued', 'converting', 'indexing', 'extracting', 'embedding']

// True while any sheet is still extracting or has annotations queued.
export function sheetsInProgress(sheets: DrawingSheetOut[] | undefined): boolean {
  return Boolean(
    sheets?.some(
      (s) =>
        (s.extraction_status != null && EXTRACTING.includes(s.extraction_status)) ||
        s.annotations_status === 'queued',
    ),
  )
}

export const SHEETS_POLL_MS = 2000

// `poll` opts a page into refetching while sheets are in progress.
export function useSheets(drawingId: string | undefined, poll = false) {
  return useQuery({
    queryKey: ['drawings', drawingId, 'sheets'],
    queryFn: ({ signal }) => api.get<DrawingSheetOut[]>(`/drawings/${drawingId}/sheets`, signal),
    enabled: Boolean(drawingId),
    refetchInterval: poll ? (query) => (sheetsInProgress(query.state.data) ? SHEETS_POLL_MS : false) : false,
  })
}

export function useAnnotations(projectId: string | undefined, drawingId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawing-annotations', drawingId],
    queryFn: ({ signal }) =>
      api.get<DrawingAnnotationPage>(
        `/projects/${projectId}/drawing-annotations?drawing_id=${drawingId}&limit=1000`,
        signal,
      ),
    enabled: Boolean(projectId) && Boolean(drawingId),
  })
}

export function useAnnotationSummary(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawing-annotations', 'summary'],
    queryFn: ({ signal }) =>
      api.get<DrawingAnnotationSummaryOut>(`/projects/${projectId}/drawing-annotations/summary`, signal),
    enabled: Boolean(projectId),
  })
}

export function useReadAnnotations(projectId: string | undefined, drawingId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (force: boolean) =>
      api.post<ReadAnnotationsOut>(`/projects/${projectId}/drawing-annotations:read`, {
        drawing_id: drawingId,
        force,
      } as ReadAnnotationsIn),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'sheets'] })
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawing-annotations'] })
    },
  })
}

export function useSheet(drawingId: string | undefined, sheetIndex: number | undefined) {
  return useQuery({
    queryKey: ['drawings', drawingId, 'sheets', sheetIndex],
    queryFn: ({ signal }) => api.get<DrawingSheetOut>(`/drawings/${drawingId}/sheets/${sheetIndex}`, signal),
    enabled: Boolean(drawingId) && sheetIndex !== undefined,
  })
}

export function useMeasurements(drawingId: string | undefined, sheetId: string | undefined) {
  return useQuery({
    queryKey: ['drawings', drawingId, 'measurements', sheetId],
    queryFn: ({ signal }) =>
      api.get<DrawingMeasurementOut[]>(`/drawings/${drawingId}/measurements?sheet_id=${sheetId}`, signal),
    enabled: Boolean(drawingId) && Boolean(sheetId),
  })
}

export function useSheetEntities(sheetId: string | undefined) {
  return useQuery({
    queryKey: ['sheets', sheetId, 'entities'],
    queryFn: ({ signal }) => api.get<DrawingEntityOut[]>(`/drawing-sheets/${sheetId}/entities`, signal),
    enabled: Boolean(sheetId),
  })
}

export function useScaleCalibrations(drawingId: string | undefined, sheetIndex: number | undefined) {
  return useQuery({
    queryKey: ['drawings', drawingId, 'sheets', sheetIndex, 'scale-calibrations'],
    queryFn: ({ signal }) =>
      api.get<SheetScaleCalibrationOut[]>(
        `/drawings/${drawingId}/sheets/${sheetIndex}/scale-calibrations`,
        signal,
      ),
    enabled: Boolean(drawingId) && sheetIndex !== undefined,
  })
}

export function useSetManualScale(drawingId: string | undefined, sheetIndex: number | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ManualScaleCalibrationIn) =>
      api.patch(`/drawings/${drawingId}/sheets/${sheetIndex}/scale`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'sheets'] })
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'measurements'] })
    },
  })
}

export function useRevertScaleCalibration(drawingId: string | undefined, sheetIndex: number | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (calibrationId: string) =>
      api.post(`/drawings/${drawingId}/sheets/${sheetIndex}/scale-calibrations/${calibrationId}/revert`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'sheets'] })
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'measurements'] })
    },
  })
}

export function useOverrideMeasurement(drawingId: string | undefined, sheetId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ measurementId, ...data }: MeasurementOverrideIn & { measurementId: string }) =>
      api.post<MeasurementOverrideOut>(`/drawing-measurements/${measurementId}/override`, data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'measurements', sheetId] }),
  })
}

export function useRevertMeasurementOverride(drawingId: string | undefined, sheetId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (measurementId: string) => api.post(`/drawing-measurements/${measurementId}/override/revert`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['drawings', drawingId, 'measurements', sheetId] }),
  })
}

// Opening a drawing starts its measuring (idempotent; also bumps it to the front of a bulk queue). Estimator+.
export function useMeasureDrawing(drawingId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<DrawingMeasureStateOut>(`/drawings/${drawingId}/measure`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['drawings', drawingId] }),
  })
}

// Bulk "Measure all": by discipline, drawing type or explicit ids. Lead estimator+.
export function useMeasureDrawings(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MeasureRequest) => api.post<MeasureOut>(`/projects/${projectId}/drawings/measure`, body),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawings'] })
    },
  })
}

export const MEASUREMENT_POLL_MS = 5000

export function measurementBusy(summary: MeasurementSummary | undefined): boolean {
  return Boolean(summary && (summary.total.queued > 0 || summary.total.measuring > 0))
}

export function useMeasurementSummary(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawings', 'measurement-summary'],
    queryFn: ({ signal }) =>
      api.get<MeasurementSummary>(`/projects/${projectId}/drawings/measurement-summary`, signal),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (measurementBusy(query.state.data) ? MEASUREMENT_POLL_MS : false),
  })
}

// Opening a drawing starts measuring it: POST /measure once when it is `indexed` (only when `canMeasure`, i.e.
// estimator+; read-only roles never call it). `failed` is retried only by an explicit click (`measure.mutate()`).
// When the drawing turns `measured` while the page is open, the sheet and measurement lists are refetched.
export function useMeasureOnOpen(drawing: DrawingOut | undefined, canMeasure: boolean) {
  const measure = useMeasureDrawing(drawing?.id)
  const queryClient = useQueryClient()
  const requested = useRef<string | null>(null)
  const sawBusy = useRef(false)
  const state = drawing?.measurement
  const id = drawing?.id
  const { mutate } = measure
  useEffect(() => {
    if (state === 'indexed' && canMeasure && id && requested.current !== id) {
      requested.current = id
      mutate()
    }
  }, [state, canMeasure, id, mutate])
  useEffect(() => {
    if (state === 'indexed' || state === 'queued' || state === 'measuring') sawBusy.current = true
    else if (state === 'measured' && sawBusy.current) {
      sawBusy.current = false
      queryClient.invalidateQueries({ queryKey: ['drawings', id] })
    }
  }, [state, id, queryClient])
  return measure
}
