import { Fragment, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { Button } from '../components/Button'
import { ConfirmModal } from '../components/ConfirmModal'
import { SkeletonRows } from '../components/Skeleton'
import { AiStatusNotice } from '../features/ai/AiStatusNotice'
import { useAiStatus } from '../features/ai/api'
import { AnnotationList } from '../features/drawings/AnnotationList'
import {
  drawingDownloadHref,
  useAnnotations,
  useDrawing,
  useReadAnnotations,
  useRetryIngest,
  useSheets,
} from '../features/drawings/api'
import type { DrawingAnnotationOut } from '../types/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

// docs/ui-design-system.md section 4.8. Drawing/extraction status
// vocabulary (backend/app/core/enums.py's DrawingStatus/extraction phases).
const STATUS_TONE: Record<string, BadgeTone> = {
  ready: 'success',
  succeeded: 'success',
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

// sheet.annotations_status -> label + tone. The label always carries the
// meaning; the tone is only reinforcement.
const ANNOTATION_BADGE: Record<string, { label: string; tone: BadgeTone }> = {
  queued: { label: 'Annotations: queued', tone: 'info' },
  done: { label: 'Annotations: read', tone: 'success' },
  unavailable: { label: 'Annotations: AI unavailable', tone: 'warning' },
  failed: { label: 'Annotations: failed', tone: 'danger' },
  skipped: { label: 'Annotations: nothing to read', tone: 'neutral' },
}
const NOT_READ = { label: 'Annotations: not read', tone: 'neutral' as BadgeTone }

// Mirrors the backend roles allowed to POST drawing-annotations:read.
const _READ_ANNOTATION_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

const NO_ANNOTATIONS: DrawingAnnotationOut[] = []

export function SheetIndexPage() {
  const { projectId, drawingId } = useParams()
  const { data: drawing } = useDrawing(drawingId)
  const { data: sheets, isLoading, isError, error } = useSheets(drawingId, true)
  const { hasRole } = useAuth()
  const retryIngest = useRetryIngest(projectId, drawingId)
  const { data: aiStatus } = useAiStatus()
  const { data: annotationPage } = useAnnotations(projectId, drawingId)
  const readAnnotations = useReadAnnotations(projectId, drawingId)
  const [confirmReread, setConfirmReread] = useState(false)
  const [queuedCount, setQueuedCount] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const annotationsBySheet = useMemo(() => {
    const map = new Map<string, DrawingAnnotationOut[]>()
    for (const a of annotationPage?.items ?? []) {
      const list = map.get(a.sheet_id)
      if (list) list.push(a)
      else map.set(a.sheet_id, [a])
    }
    return map
  }, [annotationPage])

  const total = sheets?.length ?? 0
  const extracted = sheets?.filter((s) => s.extraction_status === 'succeeded').length ?? 0
  const annotationsRead = sheets?.filter((s) => s.annotations_status === 'done').length ?? 0
  const aiUnavailable = aiStatus != null && !aiStatus.available

  function startRead(force: boolean) {
    readAnnotations.mutate(force, { onSuccess: (r) => setQueuedCount(r.queued_sheets) })
  }

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
        <div data-testid="sheet-progress" className="mt-4 space-y-1 text-sm">
          <p className="text-ink">
            {extracted} of {total} sheets extracted
          </p>
          <p className="text-ink">
            {annotationsRead} of {total} sheets have annotations read
          </p>
        </div>
      )}
      {sheets && sheets.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {hasRole(..._READ_ANNOTATION_ROLES) && (
            <>
              <Button
                size="sm"
                onClick={() => startRead(false)}
                loading={readAnnotations.isPending}
                disabled={aiUnavailable}
              >
                Read annotations with AI
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setConfirmReread(true)} disabled={aiUnavailable}>
                Re-read all
              </Button>
            </>
          )}
          {queuedCount != null && (
            <span role="status" className="text-sm text-muted">
              {queuedCount} {queuedCount === 1 ? 'sheet' : 'sheets'} queued for annotation reading
            </span>
          )}
          {aiUnavailable && (
            <span className="text-sm text-muted">Annotations cannot be read now: AI is not available.</span>
          )}
          <AiStatusNotice />
        </div>
      )}
      {readAnnotations.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {readAnnotations.error.message}
        </p>
      )}
      <ConfirmModal
        open={confirmReread}
        title="Re-read all annotations?"
        message="This asks the AI to read every sheet of this drawing again, replacing annotations already read."
        confirmLabel="Re-read all"
        onCancel={() => setConfirmReread(false)}
        onConfirm={() => {
          setConfirmReread(false)
          startRead(true)
        }}
      />
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
                <th className="font-medium">Annotations</th>
                <th className="font-medium">Takeoff</th>
              </tr>
            </thead>
            <tbody>
              {sheets.map((s) => {
                const ann = ANNOTATION_BADGE[s.annotations_status ?? ''] ?? NOT_READ
                const list = annotationsBySheet.get(s.id) ?? NO_ANNOTATIONS
                const open = expanded.has(s.id)
                return (
                <Fragment key={s.id}>
                <tr className="border-b border-row-rule hover:bg-canvas">
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
                      <Badge tone={STATUS_TONE[s.extraction_status] ?? 'neutral'}>
                        Extraction: {s.extraction_status.replace('_', ' ')}
                      </Badge>
                    ) : (
                      '--'
                    )}
                  </td>
                  <td>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={ann.tone}>{ann.label}</Badge>
                      {list.length > 0 && (
                        <button
                          type="button"
                          aria-expanded={open}
                          onClick={() => toggle(s.id)}
                          className="rounded text-xs text-muted underline hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                        >
                          {list.length} {list.length === 1 ? 'annotation' : 'annotations'}
                        </button>
                      )}
                    </div>
                  </td>
                  <td>
                    <Link
                      to={`/projects/${projectId}/drawings/${drawingId}/sheets/${s.sheet_index}`}
                      aria-label={`Open sheet ${s.sheet_index + 1} in takeoff viewer`}
                      className="rounded font-medium text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
                {open && (
                  <tr className="border-b border-row-rule">
                    <td colSpan={9} className="px-2 py-2">
                      <AnnotationList annotations={list} />
                    </td>
                  </tr>
                )}
                </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
