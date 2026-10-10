import { useState } from 'react'
import { ExternalLink, ShieldAlert } from 'lucide-react'
import { Badge } from '../../components/Badge'
import { SkeletonRows } from '../../components/Skeleton'
import { documentHref, toolLabel } from './labels'
import type { AgentPlan, AgentSection, AgentStep } from './types'

function PlanView({ plan, sections }: { plan: AgentPlan | null; sections: AgentSection[] }) {
  if (!plan || (!plan.summary && plan.sections.length === 0)) {
    return <p className="text-sm text-muted">No plan yet.</p>
  }
  const label = (id: string) => sections.find((s) => s.id === id || s.section_item_id === id)?.label ?? id
  return (
    <div>
      {plan.summary && <p className="text-sm text-ink">{plan.summary}</p>}
      <ul className="mt-2 space-y-2">
        {plan.sections.map((p) => (
          <li key={p.section_id} className="rounded bg-slate-50 p-2 text-sm">
            <p className="font-medium text-ink">{label(p.section_id)}</p>
            {p.why && <p className="text-xs text-muted">{p.why}</p>}
            {p.queries.length > 0 && (
              <p className="text-xs text-ink-2">
                <span className="text-muted">Queries: </span>
                {p.queries.join(', ')}
              </p>
            )}
            {p.folders.length > 0 && (
              <p className="text-xs text-ink-2">
                <span className="text-muted">Folders: </span>
                {p.folders.join(', ')}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function StepRow({ step }: { step: AgentStep }) {
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-muted">#{step.seq}</span>
        <span className="text-sm font-medium text-ink">{toolLabel(step.tool)}</span>
        <Badge tone={step.ok ? 'success' : 'danger'}>{step.ok ? 'OK' : 'Error'}</Badge>
        {step.injection && (
          <span title="The text of this file looked like instructions to the agent; it was warned and did not follow them.">
            <Badge tone="warning">
              <ShieldAlert className="mr-1 inline h-3 w-3 align-[-2px]" aria-hidden="true" />
              Instruction-like text was found in this file
            </Badge>
          </span>
        )}
      </div>
      {step.note && <p className="mt-1 text-sm text-ink">{step.note}</p>}
      {step.result_summary && <p className="mt-0.5 text-xs text-muted">{step.result_summary}</p>}
      {step.file_refs.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1" aria-label={`Files for step ${step.seq}`}>
          {step.file_refs.map((f, i) => (
            <li key={`${f.document_id}-${f.page}-${i}`}>
              <a
                href={documentHref(f.document_id, f.page)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded text-xs text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {f.filename}
                {f.page ? ` p.${f.page}` : ''}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function Trace({
  plan,
  sections,
  steps,
  loading,
  error,
}: {
  plan: AgentPlan | null
  sections: AgentSection[]
  steps: AgentStep[] | undefined
  loading: boolean
  error: string | null
}) {
  const [sectionId, setSectionId] = useState('')
  const shown = (steps ?? []).filter((s) => !sectionId || s.section_id === sectionId)
  return (
    <section aria-labelledby="agent-trace-h" className="rounded-card bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="agent-trace-h" className="text-section font-semibold text-ink-title">
          Trace
        </h2>
        <label className="flex items-center gap-2 text-sm text-muted">
          Filter by section
          <select
            value={sectionId}
            onChange={(e) => setSectionId(e.target.value)}
            className="rounded border border-hairline bg-white px-2 py-1 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <option value="">All sections</option>
            {sections.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <h3 className="mt-3 text-sm font-semibold text-ink-title">Plan</h3>
      <PlanView plan={plan} sections={sections} />
      <h3 className="mt-4 text-sm font-semibold text-ink-title">Steps</h3>
      {error && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      )}
      {loading ? (
        <SkeletonRows count={3} />
      ) : shown.length === 0 ? (
        <p className="mt-1 text-sm text-muted">{sectionId ? 'No steps in this section yet.' : 'No steps yet.'}</p>
      ) : (
        <ol className="divide-y divide-hairline" aria-label="Agent steps">
          {shown.map((s) => (
            <StepRow key={s.seq} step={s} />
          ))}
        </ol>
      )}
    </section>
  )
}
