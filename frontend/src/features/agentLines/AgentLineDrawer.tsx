import { useState } from 'react'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Drawer } from '../../components/Drawer'
import { ApiError } from '../../lib/api'
import { formatMoney } from '../../lib/format'
import { ConfidenceChip } from './AgentBadges'
import { useAgentConfirm } from './api'
import { flagInfo } from './constants'
import { sourceLabel } from './text'
import type { AgentEvidence, AgentLine, AgentProposal } from './types'

const msg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

type FileEvidence = Extract<AgentEvidence, { file_id: string }>
const isFile = (e: AgentEvidence): e is FileEvidence => 'file_id' in e && Boolean((e as FileEvidence).file_id)
const isSource = (e: AgentEvidence): e is Extract<AgentEvidence, { kind: 'cost_source' }> => e.kind === 'cost_source'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1 text-sm">
      <dt className="w-32 shrink-0 text-ink-2">{label}</dt>
      <dd className="min-w-0 flex-1 text-ink">{children}</dd>
    </div>
  )
}

function EvidenceList({ evidence }: { evidence: AgentEvidence[] }) {
  const files = evidence.filter(isFile)
  if (files.length === 0) return <p className="text-sm text-ink-2">No document evidence was recorded for this line.</p>
  return (
    <ul className="space-y-2">
      {files.map((e, i) => (
        <li key={`${e.file_id}-${e.page ?? ''}-${i}`} className="rounded border border-hairline px-3 py-2 text-sm">
          <a
            href={`/api/v1/tender-documents/${e.file_id}/download${e.page != null ? `#page=${e.page}` : ''}`}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all rounded font-medium text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {e.path}
            {e.page != null ? `, page ${e.page}` : ''}
          </a>
          {e.quote && <blockquote className="mt-1 border-l-2 border-row-rule pl-2 text-ink-2">{e.quote}</blockquote>}
        </li>
      ))}
    </ul>
  )
}

function DrawerBody({
  line,
  proposal,
  canAct,
  draft,
  settlementId,
  onClose,
  onReplace,
}: {
  line: AgentLine
  proposal: AgentProposal
  canAct: boolean
  draft: boolean
  settlementId: string
  onClose: () => void
  onReplace: (lineId: string) => void
}) {
  const confirm = useAgentConfirm(settlementId)
  const isEstimate = line.cost_source === 'agent_estimate'
  // An estimate has no quote behind it: Confirm waits until the evidence has been opened.
  const [evidenceSeen, setEvidenceSeen] = useState(!isEstimate)
  const [justConfirmed, setJustConfirmed] = useState(false)
  const confirmed = Boolean(line.agent_confirmed_by) || justConfirmed
  const conflict = confirm.error instanceof ApiError && confirm.error.status === 409

  const source = proposal.evidence.find(isSource)
  const rate = proposal.rate ?? line.direct_unit_cost
  const currency = proposal.currency ?? line.source_currency
  const q = proposal.qty_check

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={confirmed ? 'success' : isEstimate ? 'warning' : 'info'}>{sourceLabel({ ...line, agent_confirmed_by: confirmed ? 'x' : null })}</Badge>
        <ConfidenceChip confidence={proposal.confidence} />
      </div>

      <dl className="mt-3 divide-y divide-row-rule">
        <Row label="Rate">
          <span className="tabular-nums font-medium">{rate != null ? formatMoney(rate, currency) : '--'}</span>
          {proposal.uom ? <span className="text-ink-2"> per {proposal.uom}</span> : null}
        </Row>
        <Row label="Currency">{currency}</Row>
        <Row label="Unit">{proposal.uom ?? '--'}</Row>
        <Row label="As of">{proposal.as_of ?? '--'}</Row>
        {isEstimate ? (
          <Row label="Method">{proposal.method ?? '--'}</Row>
        ) : (
          <Row label="Source">
            {source ? (
              <>
                {source.label} <span className="text-ink-2">({source.type})</span>
              </>
            ) : (
              (proposal.candidate_ref ?? '--')
            )}
          </Row>
        )}
      </dl>

      <section aria-labelledby="agent-qty-title" className="mt-4">
        <h3 id="agent-qty-title" className="text-sm font-semibold text-ink-title">
          Quantity check
        </h3>
        {q ? (
          <p className="mt-1 text-sm text-ink">
            BOQ quantity <span className="tabular-nums font-medium">{q.boq_quantity}</span>
            {q.measured != null ? (
              <>
                , measured <span className="tabular-nums font-medium">{q.measured}</span>
                {q.unit ? ` ${q.unit}` : ''}
                {q.delta_pct != null ? ` (${q.delta_pct > 0 ? '+' : ''}${q.delta_pct}%)` : ''}
              </>
            ) : (
              ', not measured'
            )}
            {q.class ? <span className="text-ink-2">, {q.class.replace(/_/g, ' ')}</span> : null}
            <span className="block text-xs text-ink-2">For information only. The BOQ quantity is never changed.</span>
          </p>
        ) : (
          <p className="mt-1 text-sm text-ink-2">No measured quantity to compare.</p>
        )}
      </section>

      <section aria-labelledby="agent-flags-title" className="mt-4">
        <h3 id="agent-flags-title" className="text-sm font-semibold text-ink-title">
          Flags
        </h3>
        {proposal.flags.length === 0 ? (
          <p className="mt-1 text-sm text-ink-2">No flags.</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {proposal.flags.map((f) => {
              const info = flagInfo(f)
              return (
                <li key={f} className="flex items-start gap-2 text-sm">
                  <Badge tone={info.tone}>{info.label}</Badge>
                  <span className="text-ink">{info.meaning}</span>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="agent-rationale-title" className="mt-4">
        <h3 id="agent-rationale-title" className="text-sm font-semibold text-ink-title">
          Rationale
        </h3>
        <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{proposal.rationale || 'No rationale was recorded.'}</p>
      </section>

      <section aria-labelledby="agent-evidence-title" className="mt-4">
        <h3 id="agent-evidence-title" className="text-sm font-semibold text-ink-title">
          Evidence
        </h3>
        {isEstimate && !evidenceSeen ? (
          <button
            type="button"
            aria-expanded={false}
            onClick={() => setEvidenceSeen(true)}
            className="mt-1 rounded text-sm font-medium text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Show evidence ({proposal.evidence.filter(isFile).length})
          </button>
        ) : (
          <div className="mt-1">
            <EvidenceList evidence={proposal.evidence} />
          </div>
        )}
      </section>

      {confirm.isError && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {conflict ? 'This line changed while you were looking. It was reloaded: look at the new proposal again.' : msg(confirm.error)}
        </p>
      )}
      {confirmed && (
        <p role="status" className="mt-4 text-sm text-success">
          Confirmed{line.agent_confirmed_at ? ` on ${line.agent_confirmed_at.slice(0, 10)}` : ''}.
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {canAct && (
          <>
            <Button
              loading={confirm.isPending}
              disabled={!draft || confirmed || !evidenceSeen}
              onClick={() => {
                confirm.mutate(
                  { lineId: line.line_id, proposalId: proposal.id },
                  { onSuccess: () => setJustConfirmed(true) },
                )
              }}
            >
              Confirm
            </Button>
            <Button variant="secondary" disabled={!draft} onClick={() => onReplace(line.line_id)}>
              Replace
            </Button>
          </>
        )}
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      </div>
      {canAct && isEstimate && !evidenceSeen && !confirmed && (
        <p className="mt-2 text-xs text-ink-2">Open the evidence to enable Confirm. An estimate has no quote behind it.</p>
      )}
      {!canAct && <p className="mt-2 text-xs text-ink-2">Only lead estimators and above can confirm or replace agent lines.</p>}
    </div>
  )
}

/** The evidence drawer of one agent line. Confirm sends the id of the proposal shown here. */
export function AgentLineDrawer({
  line,
  settlementId,
  canAct,
  draft,
  onClose,
  onReplace,
}: {
  line: AgentLine | null
  settlementId: string
  canAct: boolean
  draft: boolean
  onClose: () => void
  onReplace: (lineId: string) => void
}) {
  const proposal = line?.proposal ?? null
  return (
    <Drawer open={line !== null} title={line ? `Agent line ${line.line_id.slice(0, 8)}` : 'Agent line'} onClose={onClose}>
      {line && !proposal && <p className="text-sm text-ink-2">This line has no agent proposal any more. Reload the page.</p>}
      {line && proposal && (
        // Keyed by proposal: a re-fetched, different proposal resets the "evidence seen" gate.
        <DrawerBody
          key={proposal.id}
          line={line}
          proposal={proposal}
          canAct={canAct}
          draft={draft}
          settlementId={settlementId}
          onClose={onClose}
          onReplace={onReplace}
        />
      )}
    </Drawer>
  )
}
