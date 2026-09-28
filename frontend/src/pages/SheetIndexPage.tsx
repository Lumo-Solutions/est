import { Link, useParams } from 'react-router-dom'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useDrawing, useSheets } from '../features/drawings/api'

// docs/ui-design-system.md section 4.8. Drawing/extraction status
// vocabulary (backend/app/core/enums.py's DrawingStatus/extraction phases).
const STATUS_TONE: Record<string, BadgeTone> = {
  ready: 'success',
  failed: 'danger',
  partial: 'warning',
  queued: 'neutral',
  indexing: 'info',
  extracting: 'info',
  embedding: 'info',
}

export function SheetIndexPage() {
  const { projectId, drawingId } = useParams()
  const { data: drawing } = useDrawing(drawingId)
  const { data: sheets, isLoading, isError, error } = useSheets(drawingId)

  return (
    <div className="p-6">
      <Link
        to={`/projects/${projectId}`}
        className="rounded text-sm text-slate-500 hover:text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        ← Back to project
      </Link>
      <h1 className="mt-2 text-xl font-semibold text-slate-800">{drawing?.original_filename ?? 'Sheets'}</h1>
      {drawing && (
        <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">
          Status: <Badge tone={STATUS_TONE[drawing.status] ?? 'neutral'}>{drawing.status}</Badge>
        </p>
      )}
      {isLoading && (
        <div className="mt-4">
          <SkeletonRows count={4} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-4 text-danger">
          {error.message}
        </p>
      )}
      {sheets && sheets.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">
          No sheets indexed yet -- extraction may still be running.
        </p>
      )}
      {sheets && sheets.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2 font-medium">#</th>
              <th className="font-medium">Drawing no.</th>
              <th className="font-medium">Title</th>
              <th className="font-medium">Revision</th>
              <th className="font-medium">Discipline</th>
              <th className="font-medium">Scale</th>
              <th className="font-medium">Extraction</th>
            </tr>
          </thead>
          <tbody>
            {sheets.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2">
                  <Link
                    to={`/projects/${projectId}/drawings/${drawingId}/sheets/${s.sheet_index}`}
                    className="rounded text-slate-800 tabular-nums hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                  >
                    {s.sheet_index + 1}
                  </Link>
                </td>
                <td>{s.drawing_number ?? '--'}</td>
                <td>{s.sheet_title ?? s.source_name ?? '--'}</td>
                <td>{s.revision ?? '--'}</td>
                <td>{s.discipline ?? '--'}</td>
                <td className="tabular-nums">
                  {s.scale_text ?? (s.scale_ratio ? `1:${Math.round(1 / s.scale_ratio)}` : '--')}
                  {s.scale_disagreement && (
                    <span className="ml-1 text-warning" title="Scale sources disagree">
                      ⚠
                    </span>
                  )}
                </td>
                <td>
                  {s.extraction_status ? (
                    <Badge tone={STATUS_TONE[s.extraction_status] ?? 'neutral'}>{s.extraction_status}</Badge>
                  ) : (
                    '--'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
