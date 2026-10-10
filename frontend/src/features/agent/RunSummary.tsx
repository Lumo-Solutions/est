import { Link } from 'react-router-dom'
import { useAgentSummary } from './api'
import { formatSeconds, formatUsd } from './labels'
import { isTerminal, type AgentRunDetail } from './types'

export function RunSummary({ run }: { run: AgentRunDetail }) {
  const finished = isTerminal(run.status)
  const confirm = useAgentSummary(run.settlement_id, finished)
  if (!finished) return null
  const s = run.summary
  const applied = s?.applied?.applied ?? 0
  const skipped = s?.applied?.skipped_person_set ?? 0
  const n = confirm.data?.unconfirmed
  return (
    <section aria-labelledby="agent-summary-h" className="rounded-card bg-white p-5">
      <h2 id="agent-summary-h" className="text-section font-semibold text-ink-title">
        Run summary
      </h2>
      {!s ? (
        <p className="mt-2 text-sm text-muted">This run ended without a summary.</p>
      ) : (
        <dl className="mt-3 grid grid-cols-2 gap-4 md:grid-cols-5">
          <Item label="Lines proposed">{s.proposals ?? 0}</Item>
          <Item label="Applied to the draft">{applied}</Item>
          <Item label="Skipped (set by a person)">{skipped}</Item>
          <Item label="Files read">
            {s.files_read ?? 0} of {s.files_in_pack ?? 0}
          </Item>
          <Item label="Time">{formatSeconds(s.seconds)}</Item>
          <Item label="Cost">{formatUsd(run.cost_usd)}</Item>
        </dl>
      )}
      {run.settlement_id && (
        <p className="mt-4 text-sm">
          <Link
            to={`/projects/${run.project_id}/settlement`}
            className="rounded text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {n == null
              ? 'Open the settlement'
              : n === 0
                ? 'Open the settlement (no lines need confirmation)'
                : `${n} ${n === 1 ? 'line needs' : 'lines need'} your confirmation before submit`}
          </Link>
        </p>
      )}
    </section>
  )
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-base font-medium tabular-nums text-ink">{children}</dd>
    </div>
  )
}
