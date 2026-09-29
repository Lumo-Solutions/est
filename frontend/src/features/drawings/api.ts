import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  DrawingEntityOut,
  DrawingMeasurementOut,
  DrawingOut,
  DrawingSheetOut,
  ManualScaleCalibrationIn,
  MeasurementOverrideIn,
  MeasurementOverrideOut,
  SheetScaleCalibrationOut,
} from '../../types/api'

export function useDrawings(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'drawings'],
    queryFn: ({ signal }) => api.get<DrawingOut[]>(`/projects/${projectId}/drawings`, signal),
    enabled: Boolean(projectId),
  })
}

export function useUploadDrawing(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      const drawing = await api.post<DrawingOut>(`/projects/${projectId}/drawings`, formData)
      await api.post(`/drawings/${drawing.id}/ingest`)
      return drawing
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'drawings'] }),
  })
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
      return status && ['queued', 'indexing', 'extracting', 'embedding'].includes(status) ? 3000 : false
    },
  })
}

export function useSheets(drawingId: string | undefined) {
  return useQuery({
    queryKey: ['drawings', drawingId, 'sheets'],
    queryFn: ({ signal }) => api.get<DrawingSheetOut[]>(`/drawings/${drawingId}/sheets`, signal),
    enabled: Boolean(drawingId),
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
