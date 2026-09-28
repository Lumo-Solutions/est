import { useId, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { useReasonCodes, useRecordOutcome } from '../features/settlement/api'
import { useCurrentSettlement } from '../features/settlement/useCurrentSettlement'
import { formatMoney } from '../lib/format'
import { Role } from '../lib/roles'

// Mirrors backend/app/api/v1/routes/settlement.py's _OUTCOME_ROLES.
const RECORD_OUTCOME_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// SettlementOutcome (won/lost).
const OUTCOME_TONE: Record<string, BadgeTone> = {
  won: 'success',
  lost: 'danger',
}

export function WinLossPage() {
  const { projectId } = useParams()
  const { hasRole } = useAuth()
  const { current, isLoading } = useCurrentSettlement(projectId)
  const { data: reasonCodes } = useReasonCodes()
  const recordOutcome = useRecordOutcome(projectId, current?.id)

  const [outcome, setOutcome] = useState<'won' | 'lost'>('won')
  const [ourPrice, setOurPrice] = useState('')
  const [winningPrice, setWinningPrice] = useState('')
  const [selectedReasonCodes, setSelectedReasonCodes] = useState<string[]>([])
  const [note, setNote] = useState('')
  const outcomeSelectId = useId()
  const reasonCodesSelectId = useId()

  if (isLoading) return <p className="p-6 text-slate-500">Loading...</p>
  if (!current) return <p className="p-6 text-sm text-slate-500">No settlement yet for this project.</p>
  const canRecordOutcome = hasRole(...RECORD_OUTCOME_ROLES)

  if (current.outcome) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-slate-800">Win / loss</h1>
        <div className="mt-4 rounded border border-slate-200 p-4 text-sm">
          <p className="flex items-center gap-2 font-semibold">
            <Badge tone={OUTCOME_TONE[current.outcome] ?? 'neutral'}>{current.outcome}</Badge>
          </p>
          <p className="mt-2 tabular-nums">
            Our price: {current.outcome_our_price != null ? formatMoney(current.outcome_our_price, current.currency) : '--'}
          </p>
          <p className="tabular-nums">
            Winning price:{' '}
            {current.outcome_winning_price != null ? formatMoney(current.outcome_winning_price, current.currency) : '--'}
          </p>
          <p>Competitors: {current.outcome_competitor_names.join(', ') || '--'}</p>
          <p>Reason codes: {current.outcome_reason_codes.join(', ') || '--'}</p>
          {current.outcome_note && <p>Note: {current.outcome_note}</p>}
        </div>
      </div>
    )
  }

  if (!canRecordOutcome) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-slate-800">Win / loss</h1>
        <p className="mt-4 text-sm text-slate-500">
          No outcome recorded yet. Only bd_director/managing_director can record it.
        </p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Win / loss</h1>
      <form
        className="mt-4 max-w-md space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          recordOutcome.mutate({
            outcome,
            our_price: ourPrice ? Number(ourPrice) : null,
            winning_price: winningPrice ? Number(winningPrice) : null,
            reason_codes: selectedReasonCodes,
            note: note || null,
          })
        }}
      >
        <div>
          <label htmlFor={outcomeSelectId} className="block text-xs text-slate-500">
            Outcome
          </label>
          <select
            id={outcomeSelectId}
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as 'won' | 'lost')}
            className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          >
            <option value="won">Won</option>
            <option value="lost">Lost</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="our-price">
            Our price
          </label>
          <input
            id="our-price"
            type="number"
            step="any"
            value={ourPrice}
            onChange={(e) => setOurPrice(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="winning-price">
            Winning price
          </label>
          <input
            id="winning-price"
            type="number"
            step="any"
            value={winningPrice}
            onChange={(e) => setWinningPrice(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label htmlFor={reasonCodesSelectId} className="block text-xs text-slate-500">
            Reason codes
          </label>
          <select
            id={reasonCodesSelectId}
            multiple
            value={selectedReasonCodes}
            onChange={(e) => setSelectedReasonCodes(Array.from(e.target.selectedOptions, (o) => o.value))}
            className="h-24 w-full rounded border border-slate-300 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {(reasonCodes ?? []).map((rc) => (
              <option key={rc.code} value={rc.code}>
                {rc.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="note">
            Note
          </label>
          <textarea
            id="note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <button
          type="submit"
          disabled={recordOutcome.isPending}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Record outcome
        </button>
        {recordOutcome.isError && (
          <p role="alert" className="text-sm text-danger">
            {recordOutcome.error.message}
          </p>
        )}
      </form>
    </div>
  )
}
