import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '../../components/Badge'
import { controlClasses } from '../../components/Field'
import type {
  VerificationEvidenceOut,
  VerificationLineOut,
  VerificationMappingAction,
} from '../../types/api'
import { useLineMapping, useVerificationEvidence } from './api'
import { CLASS_LABEL, CLASS_TONE, MAPPED_BY_LABEL, fmtPct, fmtQty, openOnDrawingPath } from './labels'

const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'
const linkBtn = `rounded text-sm hover:underline disabled:opacity-50 ${ring}`

function EvidenceRow({ projectId, e }: { projectId: string; e: VerificationEvidenceOut }) {
  return (
    <span className="text-xs text-ink-2">
      {e.kind === 'measurement' ? 'Measurement' : 'Annotation'}: {fmtQty(e.value)} {e.unit ?? ''}
      {e.label ? ` - ${e.label}` : ''} (page {e.page}){' '}
      <Link to={openOnDrawingPath(projectId, e)} className={`rounded text-brand hover:underline ${ring}`}>
        Open on drawing
      </Link>
    </span>
  )
}

function AddEvidence({
  projectId,
  onInclude,
  busy,
}: {
  projectId: string
  onInclude: (ref: string) => void
  busy: boolean
}) {
  const [q, setQ] = useState('')
  const { data, isFetching } = useVerificationEvidence(projectId, q, '', q.trim().length > 0)
  return (
    <div className="mt-2">
      <label htmlFor="ver-evidence-q" className="text-xs text-muted">
        Add evidence
      </label>
      <input
        id="ver-evidence-q"
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search measurements and annotations"
        className={`${controlClasses} mt-1 py-1.5 text-sm`}
      />
      {q.trim() && !isFetching && (data?.items ?? []).length === 0 && (
        <p className="mt-1 text-xs text-muted">No evidence found.</p>
      )}
      <ul className="mt-1 space-y-1">
        {(data?.items ?? []).map((e) => (
          <li key={e.ref} className="flex items-center justify-between gap-2">
            <EvidenceRow projectId={projectId} e={e} />
            <button
              type="button"
              disabled={busy}
              onClick={() => onInclude(e.ref)}
              aria-label={`Include ${e.label ?? e.ref}`}
              className={`${linkBtn} text-brand`}
            >
              Include
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function LineDetailPanel({
  projectId,
  runId,
  line,
  onClose,
}: {
  projectId: string
  runId: string
  line: VerificationLineOut
  onClose: () => void
}) {
  const mapping = useLineMapping(runId)
  const panelRef = useRef<HTMLDivElement>(null)

  // Focus management: move focus into the panel on open, restore on close.
  useEffect(() => {
    const opener = document.activeElement
    panelRef.current?.focus()
    return () => {
      if (opener instanceof HTMLElement) opener.focus()
    }
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
    }
  }

  const decidable = line.boq_line_item_id !== null
  const act = (action: VerificationMappingAction, evidence_ref: string) =>
    mapping.mutate({ lineId: line.id, body: { action, evidence_ref } })
  const evidenceByRef = new Map(line.evidence.map((e) => [e.ref, e]))
  const interp = line.interpretation
  const mappedLabel = MAPPED_BY_LABEL[line.mapped_by]

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label={`Line detail: ${line.item_no ?? 'no item no'}`}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="w-96 shrink-0 overflow-y-auto rounded-card bg-white p-4 focus:outline-none"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-lg font-semibold text-ink-title">
          {line.item_no ? `${line.item_no} -- ` : ''}
          {line.description}
        </h3>
        <button type="button" onClick={onClose} className={`${linkBtn} text-muted`}>
          Close
        </button>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
        <Badge tone={CLASS_TONE[line.vclass]}>{CLASS_LABEL[line.vclass]}</Badge>
        {mappedLabel && <Badge tone="neutral">{mappedLabel}</Badge>}
        <span>Confidence {(line.confidence * 100).toFixed(0)}%</span>
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-sm text-ink">
        <dt className="text-muted">BOQ quantity</dt>
        <dd className="tabular-nums">
          {fmtQty(line.boq_quantity)} {line.boq_uom ?? ''}
        </dd>
        <dt className="text-muted">Drawing quantity</dt>
        <dd className="tabular-nums">{fmtQty(line.drawing_quantity)}</dd>
        <dt className="text-muted">Delta</dt>
        <dd className="tabular-nums">
          {fmtQty(line.delta)} ({fmtPct(line.delta_pct)})
        </dd>
      </dl>
      {line.note && <p className="mt-2 text-sm text-ink-2">{line.note}</p>}
      {line.flags.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-1">
          {line.flags.map((f) => (
            <Badge key={f} tone="warning">
              {f.replace(/_/g, ' ')}
            </Badge>
          ))}
        </p>
      )}

      {interp && (
        <>
          <h4 className="mt-4 text-xs font-semibold uppercase text-muted">How this line was read</h4>
          <ul className="mt-1 text-sm text-ink-2">
            {interp.work_type && <li>Work type: {interp.work_type}</li>}
            {interp.material && <li>Material: {interp.material}</li>}
            {interp.size_mm != null && <li>Size: {interp.size_mm} mm</li>}
            {interp.unit && <li>Unit: {interp.unit}</li>}
            {interp.trade && <li>Trade: {interp.trade}</li>}
            {interp.source && <li>Read by: {interp.source}</li>}
            {interp.keywords.length > 0 && <li>Keywords: {interp.keywords.join(', ')}</li>}
          </ul>
        </>
      )}

      <h4 className="mt-4 text-xs font-semibold uppercase text-muted">Evidence used</h4>
      {line.evidence.length === 0 && <p className="text-xs text-muted">No drawing evidence used.</p>}
      <ul className="mt-1 space-y-1">
        {line.evidence.map((e) => (
          <li key={e.ref}>
            <EvidenceRow projectId={projectId} e={e} />
          </li>
        ))}
      </ul>

      {!decidable ? (
        <p className="mt-4 text-xs text-muted">
          This is drawing quantity that no BOQ line accounts for, so there is nothing to accept or reject.
          Add a BOQ line for it or confirm it is out of scope.
        </p>
      ) : (
        <>
          <h4 className="mt-4 text-xs font-semibold uppercase text-muted">Candidate evidence</h4>
          <p className="mt-1 text-xs text-muted">
            Accept confirms this evidence belongs to the line and also links the measurement into the BOQ
            reconciliation. Reject says it does not belong. Clear removes your decision.
          </p>
          {mapping.isError && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {mapping.error.message}
            </p>
          )}
          {line.candidates.length === 0 && <p className="mt-1 text-xs text-muted">No candidates.</p>}
          <ul className="mt-1 space-y-2">
            {line.candidates.map((c) => {
              const ev = evidenceByRef.get(c.ref)
              return (
                <li key={c.ref} className="rounded border border-hairline p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink">
                      {ev ? `${fmtQty(ev.value)} ${ev.unit ?? ''}` : c.ref}
                    </span>
                    <span className="text-muted">score {(c.score * 100).toFixed(0)}%</span>
                    <Badge tone={c.source === 'ai' ? 'info' : 'neutral'}>{c.source === 'ai' ? 'AI' : 'Rules'}</Badge>
                    {c.selected && <Badge tone="success">Selected</Badge>}
                  </div>
                  <p className="mt-1 text-ink-2">{c.reason}</p>
                  <span className="mt-1 flex gap-3">
                    <button
                      type="button"
                      disabled={mapping.isPending}
                      onClick={() => act('accept', c.ref)}
                      aria-label={`Accept ${c.ref}`}
                      className={`${linkBtn} text-emerald-700`}
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      disabled={mapping.isPending}
                      onClick={() => act('reject', c.ref)}
                      aria-label={`Reject ${c.ref}`}
                      className={`${linkBtn} text-danger`}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      disabled={mapping.isPending}
                      onClick={() => act('clear', c.ref)}
                      aria-label={`Clear ${c.ref}`}
                      className={`${linkBtn} text-muted`}
                    >
                      Clear
                    </button>
                  </span>
                </li>
              )
            })}
          </ul>
          <AddEvidence projectId={projectId} busy={mapping.isPending} onInclude={(ref) => act('include', ref)} />
        </>
      )}
    </div>
  )
}
