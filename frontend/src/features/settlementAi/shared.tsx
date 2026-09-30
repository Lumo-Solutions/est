import { Spinner } from '../../components/Spinner'
import type { SettlementAiRun } from '../../types/api'

export function RunProgress({ run }: { run: SettlementAiRun }) {
  if (run.status === 'queued' || run.status === 'running') {
    const pct = run.progress_total > 0 ? Math.round((run.progress_done / run.progress_total) * 100) : 0
    return (
      <p role="status" className="mt-2 inline-flex items-center gap-1.5 text-sm text-muted">
        <Spinner className="text-muted" />
        {run.status === 'queued' ? 'Queued...' : 'Working...'}{' '}
        <span className="tabular-nums">
          {run.progress_done}/{run.progress_total} ({pct}%)
        </span>
      </p>
    )
  }
  if (run.status === 'failed') {
    return (
      <p role="alert" className="mt-2 text-sm text-danger">
        The run failed{run.error ? `: ${run.error}` : '.'}
      </p>
    )
  }
  return null
}

export function RunWarnings({ run }: { run: SettlementAiRun }) {
  if (run.warnings.length === 0) return null
  return (
    <ul className="mt-2 space-y-1">
      {run.warnings.map((w) => (
        <li key={w} role="status" className="rounded bg-warning-subtle px-3 py-2 text-sm text-amber-800">
          {w}
        </li>
      ))}
    </ul>
  )
}

export function AiUsageLine({ run }: { run: SettlementAiRun | undefined }) {
  if (!run) return null
  return (
    <p className="mt-1 text-xs tabular-nums text-muted">
      AI usage: {run.ai_calls} AI call{run.ai_calls === 1 ? '' : 's'}, ${Number(run.ai_cost_usd).toFixed(2)}
    </p>
  )
}
