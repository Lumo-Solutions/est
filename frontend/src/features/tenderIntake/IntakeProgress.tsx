import { Card } from '../../components/Card'
import { displayStatusLabel, isIntakeBusy } from './treeLib'
import type { TreeSummary } from './types'

const IN_PROGRESS_STATES = ['queued', 'reading', 'classified', 'extracting']

// Live "Reading documents: X of Y" bar with a count per state.
export function IntakeProgress({ summary }: { summary: TreeSummary }) {
  if (!isIntakeBusy(summary)) return null
  const done = Math.max(0, summary.total - summary.in_progress)
  const pct = summary.total > 0 ? Math.round((done / summary.total) * 100) : 0
  const counts = IN_PROGRESS_STATES.filter((s) => (summary.by_display_status[s] ?? 0) > 0)
  return (
    <Card className="mt-6" aria-label="Reading progress">
      <p role="status" className="text-base font-medium text-ink">
        {summary.total > 0 ? `Reading documents: ${done} of ${summary.total}` : 'Unpacking your upload...'}
      </p>
      <div
        role="progressbar"
        aria-label="Documents read"
        aria-valuemin={0}
        aria-valuemax={Math.max(summary.total, 1)}
        aria-valuenow={done}
        className="mt-2 h-2.5 w-full overflow-hidden rounded-pill bg-slate-100"
      >
        <div className="h-full rounded-pill bg-brand transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      {counts.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-2">
          {counts.map((s) => (
            <li key={s}>
              {displayStatusLabel(s)}: <span className="tabular-nums">{summary.by_display_status[s]}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
