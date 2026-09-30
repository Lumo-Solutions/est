import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { drawingDownloadHref, useDrawing, useRetryIngest, useSheets } from '../features/drawings/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

// docs/ui-design-system.md section 4.8. Drawing/extraction status
// vocabulary (backend/app/core/enums.py's DrawingStatus/extraction phases).
const STATUS_TONE: Record<string, BadgeTone> = {
  ready: 'success',
  failed: 'danger',
  partial: 'warning',
  needs_conversion: 'warning',
  converting: 'info',
  queued: 'neutral',
  indexing: 'info',
  extracting: 'info',
  embedding: 'info',
}

// Mirrors backend/app/api/v1/routes/drawings.py's _UPLOAD_ROLES -- same
// roles allowed to POST /drawings/{id}/ingest in the first place.
const _RETRY_ROLES = [
  Role.ESTIMATOR,
  Role.LEAD_ESTIMATOR,
  Role.PROCUREMENT_HEAD,
  Role.BD_DIRECTOR,
  Role.MANAGING_DIRECTOR,
]

export function SheetIndexPage() {
  const { projectId, drawingId } = useParams()
  const { data: drawing } = useDrawing(drawingId)
  const { data: sheets, isLoading, isError, error } = useSheets(drawingId)
  const { hasRole } = useAuth()
  const retryIngest = useRetryIngest(projectId, drawingId)

  return (
    <div className="mx-6 my-6 rounded-card bg-white p-6 xl:mx-10">
      <Link
        to={`/projects/${projectId}`}
        className="rounded text-sm text-muted hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        ← Back to project
      </Link>
      <PageTitle>{drawing?.original_filename ?? 'Sheets'}</PageTitle>
      {drawing && (
        <p className="mt-1 flex items-center gap-2 text-sm text-muted">
          Status: <Badge tone={STATUS_TONE[drawing.status] ?? 'neutral'}>{drawing.status.replace('_', ' ')}</Badge>
          {(drawing.status === 'failed' || drawing.status === 'partial' || drawing.status === 'needs_conversion') &&
            hasRole(..._RETRY_ROLES) && (
            <button
              type="button"
              onClick={() => retryIngest.mutate()}
              disabled={retryIngest.isPending}
              className="rounded text-xs text-muted underline hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 disabled:opacity-50"
            >
              {retryIngest.isPending
                ? 'Retrying…'
                : drawing.status === 'needs_conversion'
                  ? 'Retry conversion'
                  : 'Retry extraction'}
            </button>
          )}
        </p>
      )}
      {drawing && drawing.kind === 'dwg' && (
        <p data-testid="dwg-provenance" className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-muted">
          {drawing.converted_from_dwg && <Badge tone="info">Converted from DWG</Badge>}
          <a
            href={drawingDownloadHref(drawing.id, 'original')}
            className="rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Download original DWG
          </a>
          {drawing.converted_from_dwg && (
            <>
              <a
                href={drawingDownloadHref(drawing.id, 'derived')}
                className="rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Download converted DXF
              </a>
              <span>
                {drawing.conversion_target} via ODA File Converter {drawing.converter_version}
                {drawing.conversion_ms != null && `, ${(drawing.conversion_ms / 1000).toFixed(1)}s`}
              </span>
            </>
          )}
        </p>
      )}
      {drawing?.error_message &&
        (drawing.status === 'failed' || drawing.status === 'partial' || drawing.status === 'needs_conversion') && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {drawing.error_message}
        </p>
      )}
      {retryIngest.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {retryIngest.error.message}
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
        <p className="mt-4 text-sm text-muted">
          No sheets indexed yet -- extraction may still be running.
        </p>
      )}
      {sheets && sheets.length > 0 && (
        <div className="relative overflow-x-auto rounded-card bg-white p-2">
          <table className="mt-4 w-full text-left text-sm">
            <thead className="border-b border-hairline text-muted">
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
                <tr key={s.id} className="border-b border-row-rule hover:bg-canvas">
                  <td className="py-2">
                    <Link
                      to={`/projects/${projectId}/drawings/${drawingId}/sheets/${s.sheet_index}`}
                      className="rounded text-ink tabular-nums hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
                      <span className="ml-1 text-amber-800" title="Scale sources disagree">
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
        </div>
      )}
    </div>
  )
}
