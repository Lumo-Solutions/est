import { Card } from '../../components/Card'
import { displayStatusLabel } from './treeLib'
import type { PackageProgress, TreeSummary } from './types'

const IN_PROGRESS_STATES = ['queued', 'reading', 'classified', 'extracting']

function Bar({ label, now, max }: { label: string; now: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round((now / max) * 100)) : 0
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.max(max, 1)}
      aria-valuenow={now}
      className="mt-2 h-2.5 w-full overflow-hidden rounded-pill bg-slate-100"
    >
      <div className="h-full rounded-pill bg-brand transition-all duration-300" style={{ width: `${pct}%` }} />
    </div>
  )
}

// What the project is doing right now, from counts only: files arriving ("Uploaded U of E files"), files being read
// ("Reading documents: D of T" with a count per state), and a paused banner.
export function IntakeProgress({ summary, packages = [] }: { summary: TreeSummary; packages?: PackageProgress[] }) {
  const uploading = packages.filter((p) => p.status === 'uploading')
  const arriving = uploading.length > 0 ? uploading : packages.filter((p) => p.pending_upload > 0)
  const showUpload = summary.pending_upload > 0 || uploading.length > 0
  const uploaded = arriving.reduce((n, p) => n + p.uploaded, 0)
  const expected = arriving.reduce((n, p) => n + p.expected_count, 0)
  const unfinished = uploading.filter((p) => p.pending_upload === 0 && p.registered < p.expected_count)
  const paused = packages.filter((p) => p.status === 'paused')
  const showReading = summary.in_progress > 0 || summary.packages_processing > 0

  if (!showUpload && !showReading && paused.length === 0) return null

  const done = Math.max(0, summary.total - summary.in_progress)
  const counts = IN_PROGRESS_STATES.filter((s) => (summary.by_display_status[s] ?? 0) > 0)

  return (
    <Card className="mt-6" aria-label="Reading progress">
      {paused.length > 0 && (
        <p role="status" className="mb-2 rounded-control bg-warning-subtle px-3 py-2 text-sm font-medium text-ink">
          {paused.length === 1 ? 'This pack is paused.' : `${paused.length} packs are paused.`} Nothing new is read or uploaded until it is resumed.
        </p>
      )}
      {showUpload && (
        <div>
          <p role="status" className="text-base font-medium text-ink">
            Uploaded {uploaded} of {expected} files
          </p>
          <Bar label="Files uploaded" now={uploaded} max={expected} />
          {unfinished.map((p) => (
            <p key={p.id} className="mt-2 text-sm text-ink">
              This upload was not finished ({p.uploaded} of {p.expected_count} files arrived). Drop the same folder again under &lsquo;Add more files&rsquo; to
              continue.
            </p>
          ))}
        </div>
      )}
      {showReading && (
        <div className={showUpload ? 'mt-4' : ''}>
          <p role="status" className="text-base font-medium text-ink">
            {summary.total > 0 ? `Reading documents: ${done} of ${summary.total}` : 'Unpacking your upload...'}
          </p>
          <Bar label="Documents read" now={done} max={summary.total} />
          {counts.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-2">
              {counts.map((s) => (
                <li key={s}>
                  {displayStatusLabel(s)}: <span className="tabular-nums">{summary.by_display_status[s]}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}
