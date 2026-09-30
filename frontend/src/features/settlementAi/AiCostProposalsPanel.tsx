import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Badge, type BadgeTone } from '../../components/Badge'
import { ConfirmModal } from '../../components/ConfirmModal'
import { Spinner } from '../../components/Spinner'
import { AiStatusNotice } from '../ai/AiStatusNotice'
import { formatMoney } from '../../lib/format'
import type { CostCandidate, CostProposal, CostProposalStatus } from '../../types/api'
import { type ProposalFilters, useBulkAccept, useCostProposals, useDecideProposal, useTrackedRun } from './api'
import { AI_RUN_ROLES, flagInfo } from './constants'
import { AiUsageLine, RunProgress, RunWarnings } from './shared'

export const BULK_ACCEPT_THRESHOLD = 0.85

const STATUS_TONE: Record<CostProposalStatus, BadgeTone> = {
  proposed: 'info',
  accepted: 'success',
  overridden: 'warning',
  rejected: 'neutral',
}
const STATUS_LABEL: Record<CostProposalStatus, string> = {
  proposed: 'Awaiting decision',
  accepted: 'Accepted',
  overridden: 'Other source used',
  rejected: 'Rejected',
}
const TYPE_LABEL: Record<CostCandidate['type'], string> = { quote: 'Quote', library: 'Library', historical: 'Historical' }

const BUTTON_OUTLINE =
  'inline-flex items-center gap-1 rounded-pill border border-brand px-3 py-1 text-xs text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'
const BUTTON_SOLID =
  'inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'
const INPUT =
  'rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink'

function FlagBadges({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null
  return (
    <>
      {flags.map((f) => {
        const { label, tone } = flagInfo(f)
        return (
          <Badge key={f} tone={tone}>
            {label}
          </Badge>
        )
      })}
    </>
  )
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
      <span
        role="meter"
        aria-label="Confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="inline-block h-1.5 w-16 overflow-hidden rounded bg-slate-100"
      >
        <span className="block h-full bg-brand" style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums">{pct}%</span>
    </span>
  )
}

function ageText(c: CostCandidate): string | null {
  if (c.detail.age_months != null) return `${c.detail.age_months} month${c.detail.age_months === 1 ? '' : 's'} old`
  return c.as_of ? `as of ${c.as_of}` : null
}

function CandidateSummary({ c }: { c: CostCandidate }) {
  const age = ageText(c)
  return (
    <span className="text-sm">
      <Badge tone="neutral">{TYPE_LABEL[c.type]}</Badge> <span className="font-medium">{c.label}</span> --{' '}
      <span className="tabular-nums">{formatMoney(c.rate, c.currency)}</span> / {c.uom}
      {c.vendor && <span className="text-ink-2"> -- {c.vendor}</span>}
      {age && <span className="text-muted"> -- {age}</span>}
    </span>
  )
}

function ManualForm({ proposal, currency, onSubmit, pending }: { proposal: CostProposal; currency: string; onSubmit: (cost: number, note: string) => void; pending: boolean }) {
  const [cost, setCost] = useState('')
  const [note, setNote] = useState('')
  const valid = cost !== '' && Number.isFinite(Number(cost)) && Number(cost) >= 0 && note.trim() !== ''
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2 border-t border-row-rule pt-2">
      <div>
        <label className="mb-1 block text-sm text-ink" htmlFor={`ai-cost-${proposal.id}`}>
          Manual unit cost ({currency})
        </label>
        <input id={`ai-cost-${proposal.id}`} value={cost} onChange={(e) => setCost(e.target.value)} className={`w-32 ${INPUT}`} />
      </div>
      <div>
        <label className="mb-1 block text-sm text-ink" htmlFor={`ai-note-${proposal.id}`}>
          Why (required)
        </label>
        <input
          id={`ai-note-${proposal.id}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. budget estimate, no quote yet"
          className={`w-56 ${INPUT}`}
        />
      </div>
      <button type="button" disabled={!valid || pending} onClick={() => onSubmit(Number(cost), note.trim())} className={BUTTON_OUTLINE}>
        {pending && <Spinner className="h-3 w-3" />}
        Set manual cost
      </button>
    </div>
  )
}

function ProposalRow({ proposal, projectId, settlementId, currency }: { proposal: CostProposal; projectId: string; settlementId: string; currency: string }) {
  const decide = useDecideProposal(projectId, settlementId)
  const [showCandidates, setShowCandidates] = useState(false)
  const [showManual, setShowManual] = useState(proposal.no_source && proposal.status === 'proposed')
  const open = proposal.status === 'proposed'
  const others = proposal.candidates.filter((c) => c.ref !== proposal.chosen?.ref)
  const busy = decide.isPending

  return (
    <li className="rounded border border-hairline px-3 py-2 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className="font-medium">{proposal.item_no ?? '--'}</span> {proposal.description}{' '}
          <span className="text-xs text-muted tabular-nums">
            ({proposal.quantity} {proposal.uom ?? ''})
          </span>
        </div>
        <Badge tone={STATUS_TONE[proposal.status]}>{STATUS_LABEL[proposal.status]}</Badge>
      </div>

      {proposal.no_source || !proposal.chosen ? (
        <p className="mt-1 text-sm font-medium text-amber-800">No cost source: manual entry required</p>
      ) : (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <CandidateSummary c={proposal.chosen} />
          <ConfidenceMeter value={proposal.confidence} />
          <Badge tone={proposal.source === 'ai' ? 'info' : 'neutral'}>{proposal.source === 'ai' ? 'AI-matched' : 'Rules'}</Badge>
        </div>
      )}
      {proposal.rationale && <p className="mt-1 text-xs text-ink-2">{proposal.rationale}</p>}
      {(proposal.flags.length > 0 || (proposal.chosen && proposal.chosen.flags.length > 0)) && (
        <div className="mt-1 flex flex-wrap gap-1">
          <FlagBadges flags={Array.from(new Set([...proposal.flags, ...(proposal.chosen?.flags ?? [])]))} />
        </div>
      )}

      {!open && (
        <p className="mt-1 text-xs text-muted">
          {STATUS_LABEL[proposal.status]}
          {proposal.decided_by ? ` by ${proposal.decided_by}` : ''}
          {proposal.decided_at ? ` on ${new Date(proposal.decided_at).toLocaleString()}` : ''}
          {proposal.decision_note ? ` -- ${proposal.decision_note}` : ''}
        </p>
      )}

      {open && (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {proposal.chosen && !proposal.no_source && (
              <button type="button" disabled={busy} onClick={() => decide.mutate({ proposalId: proposal.id, data: { action: 'accept' } })} className={BUTTON_OUTLINE}>
                Accept
              </button>
            )}
            <button type="button" onClick={() => setShowManual((v) => !v)} className={BUTTON_OUTLINE}>
              Enter cost manually
            </button>
            <button type="button" disabled={busy} onClick={() => decide.mutate({ proposalId: proposal.id, data: { action: 'reject' } })} className={BUTTON_OUTLINE}>
              Reject
            </button>
            {others.length > 0 && (
              <button
                type="button"
                aria-expanded={showCandidates}
                onClick={() => setShowCandidates((v) => !v)}
                className="rounded text-xs text-ink-2 underline transition-colors duration-150 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {showCandidates ? 'Hide' : 'Show'} {others.length} other source{others.length === 1 ? '' : 's'}
              </button>
            )}
            {busy && <Spinner className="h-3 w-3" />}
          </div>
          {showCandidates && (
            <ul className="mt-2 space-y-1 border-t border-row-rule pt-2">
              {others.map((c) => (
                <li key={c.ref} className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <CandidateSummary c={c} />
                    {c.flags.length > 0 && (
                      <span className="ml-2 inline-flex flex-wrap gap-1">
                        <FlagBadges flags={c.flags} />
                      </span>
                    )}
                    {c.reason && <p className="text-xs text-ink-2">{c.reason}</p>}
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Use this instead: ${c.label}`}
                    onClick={() => decide.mutate({ proposalId: proposal.id, data: { action: 'choose', candidate_ref: c.ref } })}
                    className={BUTTON_OUTLINE}
                  >
                    Use this instead
                  </button>
                </li>
              ))}
            </ul>
          )}
          {showManual && (
            <ManualForm
              proposal={proposal}
              currency={currency}
              pending={busy}
              onSubmit={(cost, note) =>
                decide.mutate({ proposalId: proposal.id, data: { action: 'manual', manual_unit_cost: cost, manual_currency: currency, note } })
              }
            />
          )}
        </>
      )}
      {decide.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {decide.error.message}
        </p>
      )}
    </li>
  )
}

type View = 'all' | 'needs_decision' | 'flagged' | 'no_source'
type Band = 'any' | 'high' | 'medium' | 'low'

function filtersFor(view: View, band: Band): ProposalFilters {
  const f: ProposalFilters = {}
  if (view === 'needs_decision') f.status = 'proposed'
  if (view === 'flagged') f.flagged = true
  if (view === 'no_source') f.noSource = true
  if (band === 'high') f.minConfidence = BULK_ACCEPT_THRESHOLD
  if (band === 'medium') {
    f.minConfidence = 0.6
    f.maxConfidence = BULK_ACCEPT_THRESHOLD
  }
  if (band === 'low') f.maxConfidence = 0.6
  return f
}

export function AiCostProposalsPanel({ projectId, settlementId, currency }: { projectId: string; settlementId: string; currency: string }) {
  const { hasRole } = useAuth()
  const queryClient = useQueryClient()
  const canRun = hasRole(...AI_RUN_ROLES)
  const { run, start, starting, startError } = useTrackedRun(settlementId, 'costs')
  const [useAi, setUseAi] = useState(true)
  const [view, setView] = useState<View>('needs_decision')
  const [band, setBand] = useState<Band>('any')
  const [search, setSearch] = useState('')
  const [confirmBulk, setConfirmBulk] = useState(false)
  const bulk = useBulkAccept(projectId, settlementId)
  const proposals = useCostProposals(settlementId, filtersFor(view, band))

  const status = run?.status
  useEffect(() => {
    if (status === 'ready') queryClient.invalidateQueries({ queryKey: ['settlement-ai', settlementId, 'proposals'] })
  }, [status, settlementId, queryClient])

  const items = (proposals.data?.items ?? []).filter((p) => {
    const q = search.trim().toLowerCase()
    return !q || `${p.item_no ?? ''} ${p.description}`.toLowerCase().includes(q)
  })
  const counts = run?.counts
  // Estimators cannot start a run; they only see the panel once a run exists.
  if (!canRun && !run && proposals.data && proposals.data.total === 0) return null

  return (
    <div className="mt-4 border-t border-hairline pt-4">
      <h3 className="text-lg font-semibold text-ink-title">AI cost proposals</h3>
      <p className="mt-1 text-xs text-muted">
        Advice only. Accepting a proposal applies that cost to the settlement line through the normal rules and is recorded in the audit
        trail.
      </p>

      {canRun && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <AiStatusNotice />
          <button type="button" disabled={starting} onClick={() => start(useAi)} className={BUTTON_SOLID}>
            {starting && <Spinner className="text-white" />}
            Propose costs with AI
          </button>
          <label className="inline-flex items-center gap-1.5 text-sm text-ink">
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} className="accent-brand" />
            Use AI
          </label>
        </div>
      )}
      {startError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {startError}
        </p>
      )}
      {run && <RunProgress run={run} />}
      {run && <RunWarnings run={run} />}
      {run && run.status === 'ready' && counts && (
        <p className="mt-2 text-sm tabular-nums">
          {counts.lines ?? 0} lines: {counts.with_source ?? 0} with a source, {counts.no_source ?? 0} need manual entry, {counts.blocked ?? 0}{' '}
          flagged
        </p>
      )}
      <AiUsageLine run={run} />

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="ai-view" className="mb-1 block text-xs text-ink">
            Show
          </label>
          <select id="ai-view" value={view} onChange={(e) => setView(e.target.value as View)} className={INPUT}>
            <option value="all">All lines</option>
            <option value="needs_decision">Needs decision</option>
            <option value="flagged">Flagged</option>
            <option value="no_source">No source</option>
          </select>
        </div>
        <div>
          <label htmlFor="ai-band" className="mb-1 block text-xs text-ink">
            Confidence
          </label>
          <select id="ai-band" value={band} onChange={(e) => setBand(e.target.value as Band)} className={INPUT}>
            <option value="any">Any</option>
            <option value="high">High (85% and above)</option>
            <option value="medium">Medium (60-85%)</option>
            <option value="low">Low (under 60%)</option>
          </select>
        </div>
        <div>
          <label htmlFor="ai-search" className="mb-1 block text-xs text-ink">
            Search
          </label>
          <input id="ai-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Item no or description" className={`w-56 ${INPUT}`} />
        </div>
        {canRun && (
          <button type="button" disabled={bulk.isPending} onClick={() => setConfirmBulk(true)} className={BUTTON_OUTLINE}>
            {bulk.isPending && <Spinner className="h-3 w-3" />}
            Accept all high-confidence
          </button>
        )}
      </div>
      {bulk.isSuccess && (
        <p role="status" className="mt-2 text-sm tabular-nums text-emerald-700">
          Accepted {bulk.data.accepted} line{bulk.data.accepted === 1 ? '' : 's'}, skipped {bulk.data.skipped}.
        </p>
      )}
      {bulk.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {bulk.error.message}
        </p>
      )}

      {proposals.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {proposals.error.message}
        </p>
      )}
      {proposals.data && items.length === 0 && <p className="mt-2 text-sm text-muted">No lines match these filters.</p>}
      {items.length > 0 && (
        <ul className="mt-2 space-y-2">
          {items.map((p) => (
            <ProposalRow key={p.id} proposal={p} projectId={projectId} settlementId={settlementId} currency={currency} />
          ))}
        </ul>
      )}
      {proposals.data && proposals.data.total > proposals.data.items.length && (
        <p className="mt-2 text-xs text-muted">
          Showing the first {proposals.data.items.length} of {proposals.data.total} lines. Narrow the filters to see others.
        </p>
      )}

      <ConfirmModal
        open={confirmBulk}
        title="Accept all high-confidence"
        message={`Accepts every proposal with a chosen source, confidence of ${Math.round(BULK_ACCEPT_THRESHOLD * 100)}% or more and no blocking flag. Flagged lines are skipped and stay for you to decide. Each accepted cost is applied to its settlement line through the normal rules and recorded in the audit trail.`}
        confirmLabel="Accept all"
        onCancel={() => setConfirmBulk(false)}
        onConfirm={() => {
          setConfirmBulk(false)
          bulk.mutate(BULK_ACCEPT_THRESHOLD)
        }}
      />
    </div>
  )
}
