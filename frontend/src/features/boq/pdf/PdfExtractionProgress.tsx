import { Badge } from '../../../components/Badge'
import type { BadgeTone } from '../../../components/Badge'
import { Button } from '../../../components/Button'
import type { BoqPdfExtractionDetail, BoqPdfPageStatus } from '../../../types/api'

const PAGE_STATUS_LABEL: Record<BoqPdfPageStatus, string> = {
  table: 'Table read',
  ai: 'AI-read, needs review',
  skipped_collection: 'Collection page skipped',
  empty: 'No rows',
  needs_ai: 'Not read (AI unavailable)',
  ai_unavailable: 'Not read (AI unavailable)',
}

const PAGE_STATUS_TONE: Record<BoqPdfPageStatus, BadgeTone> = {
  table: 'success',
  ai: 'warning',
  skipped_collection: 'neutral',
  empty: 'neutral',
  needs_ai: 'danger',
  ai_unavailable: 'danger',
}

export function PdfExtractionProgress({
  extraction,
  onRetry,
  retrying = false,
  retryError,
}: {
  extraction: BoqPdfExtractionDetail
  onRetry?: () => void
  retrying?: boolean
  retryError?: string | null
}) {
  const total = extraction.pages_total ?? 0
  const done = extraction.pages_done ?? 0
  const running = extraction.status === 'queued' || extraction.status === 'running'
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  const pages = extraction.pages.filter((p) => p.status)

  return (
    <div className="mt-4" data-testid="pdf-progress">
      {extraction.warnings.length > 0 && (
        <div role="alert" className="mb-3 rounded bg-warning-subtle px-3 py-2 text-sm text-amber-800">
          <p className="font-medium">Check these before importing</p>
          <ul className="mt-1 list-disc pl-5">
            {extraction.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {running && (
        <div>
          <p role="status" className="text-sm text-ink">
            {extraction.status === 'queued' ? 'Waiting to start.' : 'Reading the PDF.'}{' '}
            {total > 0 ? `${done} of ${total} pages read` : 'Counting pages'}
          </p>
          <div
            role="progressbar"
            aria-label="Pages read"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={done}
            className="mt-2 h-2 max-w-lg overflow-hidden rounded-pill bg-slate-100"
          >
            <div className="h-full bg-brand transition-all duration-150" style={{ width: `${percent}%` }} />
          </div>
        </div>
      )}

      {extraction.status === 'failed' && (
        <div>
          <p role="alert" className="text-sm text-danger">
            The PDF could not be read{extraction.error ? `: ${extraction.error}` : '.'}
          </p>
          {onRetry && (
            <Button variant="secondary" size="sm" className="mt-2" loading={retrying} onClick={onRetry}>
              Retry
            </Button>
          )}
          {retryError && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {retryError}
            </p>
          )}
        </div>
      )}

      {(extraction.status === 'ready' || extraction.status === 'committed') && (
        <p role="status" className="text-sm text-ink-2">
          Finished reading {total} {total === 1 ? 'page' : 'pages'}.
        </p>
      )}

      {pages.length > 0 && (
        <ul className="mt-3 grid max-w-2xl grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2" aria-label="Page results">
          {pages.map((p) => (
            <li key={p.page} className="flex items-center justify-between gap-2">
              <span className="tabular-nums text-ink-2">Page {p.page}</span>
              <Badge tone={PAGE_STATUS_TONE[p.status]}>{PAGE_STATUS_LABEL[p.status]}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
