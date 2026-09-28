import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  useDrawing,
  useMeasurements,
  useSheet,
  useSheetEntities,
} from '../features/drawings/api'
import { CalibrationPanel } from '../features/takeoff/CalibrationPanel'
import { DxfSheetView } from '../features/takeoff/DxfSheetView'
import { MeasurementPanel } from '../features/takeoff/MeasurementPanel'
import { PdfSheetView } from '../features/takeoff/PdfSheetView'

export function TakeoffViewerPage() {
  const { projectId, drawingId, sheetIndex: sheetIndexParam } = useParams()
  const sheetIndex = Number(sheetIndexParam)
  const [selectedMeasurementId, setSelectedMeasurementId] = useState<string | null>(null)
  const [calibrating, setCalibrating] = useState(false)
  const [calibrationPoints, setCalibrationPoints] = useState<[number, number][]>([])

  const { data: drawing, isError: drawingError, error: drawingErr } = useDrawing(drawingId)
  const {
    data: sheet,
    isLoading: sheetLoading,
    isError: sheetError,
    error: sheetErr,
  } = useSheet(drawingId, sheetIndex)
  const { data: entities } = useSheetEntities(sheet?.id)
  const { data: measurements } = useMeasurements(drawingId, sheet?.id)

  if (sheetError || drawingError) {
    return (
      <div className="p-6">
        <Link
          to={`/projects/${projectId}/drawings/${drawingId}`}
          className="rounded text-sm text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          ← Sheets
        </Link>
        <p role="alert" className="mt-4 text-danger">
          {(sheetErr ?? drawingErr)?.message}
        </p>
      </div>
    )
  }
  if (sheetLoading || !sheet || !drawing) return <p className="p-6 text-slate-500">Loading...</p>

  const selectedMeasurement = measurements?.find((m) => m.id === selectedMeasurementId) ?? null

  const handlePointClick = (point: [number, number]) => {
    if (!calibrating) return
    setCalibrationPoints((prev) => (prev.length >= 2 ? [point] : [...prev, point]))
  }

  return (
    <div className="flex h-[calc(100vh-49px)]">
      <div className="flex-1 overflow-auto bg-slate-100">
        {sheet.is_raster === false && drawing.kind === 'dxf' ? (
          <DxfSheetView
            entities={entities ?? []}
            measurements={measurements ?? []}
            selectedMeasurementId={selectedMeasurementId}
            onSelectMeasurement={setSelectedMeasurementId}
            onPointClick={calibrating ? handlePointClick : undefined}
          />
        ) : (
          <PdfSheetView
            downloadUrl={`/api/v1/drawings/${drawingId}/download`}
            pageNumber={sheetIndex + 1}
            measurements={measurements ?? []}
            selectedMeasurementId={selectedMeasurementId}
            onSelectMeasurement={setSelectedMeasurementId}
            onPointClick={calibrating ? handlePointClick : undefined}
          />
        )}
      </div>
      <div className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white">
        <div className="p-4">
          <Link
            to={`/projects/${projectId}/drawings/${drawingId}`}
            className="rounded text-xs text-slate-500 hover:text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            ← Sheets
          </Link>
          <h2 className="mt-1 text-sm font-semibold text-slate-800">
            {sheet.sheet_title ?? sheet.source_name ?? `Sheet ${sheetIndex + 1}`}
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {sheet.drawing_number ?? '--'} · Rev {sheet.revision ?? '--'}
          </p>
          {sheet.scale_disagreement && (
            <p className="mt-1 text-xs text-warning">⚠ Scale sources disagree -- verify calibration.</p>
          )}
        </div>

        <div className="border-t border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-800">Measurements</h3>
          {(measurements ?? []).length === 0 && <p className="mt-1 text-xs text-slate-500">None yet.</p>}
          <ul className="mt-1 space-y-1">
            {(measurements ?? []).map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => setSelectedMeasurementId(m.id)}
                  className={`w-full rounded px-2 py-1 text-left text-xs tabular-nums transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
                    m.id === selectedMeasurementId ? 'bg-brand-subtle text-brand font-medium' : 'hover:bg-slate-50'
                  }`}
                >
                  {m.kind}: {m.effective_value} {m.unit}
                </button>
              </li>
            ))}
          </ul>
        </div>

        {selectedMeasurement && drawingId && (
          <MeasurementPanel measurement={selectedMeasurement} drawingId={drawingId} sheetId={sheet.id} />
        )}

        {drawingId && (
          <CalibrationPanel
            drawingId={drawingId}
            sheetIndex={sheetIndex}
            calibrating={calibrating}
            onCalibratingChange={setCalibrating}
            points={calibrationPoints}
            onResetPoints={() => setCalibrationPoints([])}
          />
        )}
      </div>
    </div>
  )
}
