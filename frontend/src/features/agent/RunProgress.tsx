import { Pause, Play, X } from 'lucide-react'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { formatUsd, READ_ONLY_REASON, RUN_STATUS_LABEL, RUN_STATUS_TONE, SECTION_TONE, sectionStatusLabel } from './labels'
import { isTerminal, type AgentRunDetail, type RunAction } from './types'

const CAN_PAUSE = ['queued', 'planning', 'running']

export function RunProgress({
  run,
  canAct,
  busy,
  error,
  onAction,
  onReview,
}: {
  run: AgentRunDetail
  canAct: boolean
  busy: boolean
  error: string | null
  onAction: (a: RunAction) => void
  onReview: () => void
}) {
  const terminal = isTerminal(run.status)
  const limits = run.limits
  return (
    <section aria-labelledby="agent-progress-h" className="rounded-card bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 id="agent-progress-h" className="text-section font-semibold text-ink-title">
            Progress
          </h2>
          <Badge tone={RUN_STATUS_TONE[run.status]}>{RUN_STATUS_LABEL[run.status]}</Badge>
        </div>
        {canAct ? (
          <div className="flex flex-wrap gap-2">
            {run.status === 'awaiting_confirm' && (
              <Button size="sm" onClick={onReview}>
                Review cost estimate
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || !CAN_PAUSE.includes(run.status)}
              onClick={() => onAction('pause')}
            >
              <Pause className="h-4 w-4" aria-hidden="true" />
              Pause
            </Button>
            <Button size="sm" variant="secondary" disabled={busy || run.status !== 'paused'} onClick={() => onAction('resume')}>
              <Play className="h-4 w-4" aria-hidden="true" />
              Resume
            </Button>
            <Button size="sm" variant="destructive" disabled={busy || terminal} onClick={() => onAction('cancel')}>
              <X className="h-4 w-4" aria-hidden="true" />
              Cancel run
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted">{READ_ONLY_REASON.replace('do this', 'control a run')}</p>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      {run.error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {run.error}
        </p>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Cost so far">
          {formatUsd(run.cost_usd)}
          {limits ? ` / ${formatUsd(limits.max_usd)}` : ''}
        </Stat>
        <Stat label="Steps">
          {run.steps_total}
          {limits ? ` / ${limits.max_steps}` : ''}
        </Stat>
        <Stat label="Page views">
          {run.page_views}
          {limits ? ` / ${limits.max_page_views}` : ''}
        </Stat>
        <Stat label="Sections">{run.sections.length}</Stat>
      </dl>
      {run.sections.length === 0 ? (
        <p className="mt-4 text-sm text-muted">No sections yet. The agent is still planning.</p>
      ) : (
        <ul className="mt-4 divide-y divide-hairline" aria-label="Sections">
          {[...run.sections]
            .sort((a, b) => a.seq - b.seq)
            .map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="min-w-0 truncate text-ink">{s.label}</span>
                <span className="flex items-center gap-3">
                  <span className="text-xs tabular-nums text-muted">
                    {s.steps} {s.steps === 1 ? 'step' : 'steps'}
                  </span>
                  <Badge tone={SECTION_TONE[s.status]}>{sectionStatusLabel(s.status, s.stop_reason)}</Badge>
                </span>
              </li>
            ))}
        </ul>
      )}
    </section>
  )
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-base font-medium tabular-nums text-ink">{children}</dd>
    </div>
  )
}
