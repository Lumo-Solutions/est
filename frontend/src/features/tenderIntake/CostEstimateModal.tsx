import { useState } from 'react'
import { Modal } from '../../components/Modal'
import { useConfirmCost } from './api'
import { CostConfirmationRequiredError, type CostEstimate } from './types'

/** USD to 2 decimals; "< $0.01" for a real but tiny amount. */
function formatUsd(n: number): string {
  if (n > 0 && n < 0.01) return '< $0.01'
  return `$${n.toFixed(2)}`
}

const th = 'px-2 py-1 text-left text-xs font-medium uppercase tracking-wide text-slate-500'
const thNum = 'px-2 py-1 text-right text-xs font-medium uppercase tracking-wide text-slate-500'
const num = 'px-2 py-1 text-right tabular-nums'
const UNVERIFIED_HELP = 'Price not yet checked against your provider invoice.'

function Unverified() {
  return (
    <span className="ml-1 rounded-pill bg-warning-subtle px-1.5 py-0.5 text-xs font-medium text-ink" title={UNVERIFIED_HELP}>
      unverified
    </span>
  )
}

// "Estimated AI cost" for reading a pack: shown before an external AI provider is used, and the person's OK
// (the exact total shown) is recorded server-side. If the estimate grew in the meantime, the new numbers replace
// the old ones and nothing is confirmed.
export function CostEstimateModal({
  open,
  packageId,
  projectId,
  estimate,
  onClose,
  onConfirmed,
}: {
  open: boolean
  packageId: string
  projectId?: string
  estimate: CostEstimate
  onClose: () => void
  onConfirmed?: () => void
}) {
  const confirm = useConfirmCost(projectId)
  const [source, setSource] = useState(estimate)
  const [shown, setShown] = useState(estimate)
  const [changed, setChanged] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (source !== estimate) {
    // A new estimate from the parent replaces whatever is shown.
    setSource(estimate)
    setShown(estimate)
    setChanged(false)
    setError(null)
  }

  const est = shown
  const internal = !est.external

  const onConfirm = () => {
    setError(null)
    confirm.mutate(
      { packageId, accepted_usd: est.total_usd },
      {
        onSuccess: () => {
          onClose()
          onConfirmed?.()
        },
        onError: (e) => {
          if (e instanceof CostConfirmationRequiredError && e.estimate) {
            setShown(e.estimate)
            setChanged(true)
          } else {
            setError(e instanceof Error ? e.message : 'Request failed')
          }
        },
      },
    )
  }

  return (
    <Modal open={open} title="Estimated AI cost" onClose={onClose}>
      {changed && (
        <p role="status" className="mt-2 rounded-control bg-warning-subtle px-3 py-2 text-sm font-medium text-ink">
          The estimate changed since you last looked. Review the new numbers before confirming.
        </p>
      )}
      {internal ? (
        <p className="mt-2 text-sm text-ink">
          <span className="font-medium">No per-call cost.</span> This pack is read by {est.provider}, which is not an external provider.
        </p>
      ) : (
        <>
          <p className="mt-2 text-sm text-ink">
            Total:{' '}
            <span className="text-base font-semibold tabular-nums">{formatUsd(est.total_usd)}</span>
            {est.any_unverified && <Unverified />}
          </p>
          <p className="mt-1 text-sm text-ink-2">
            Files needing AI: <span className="tabular-nums font-medium">{est.files_needing_ai}</span>
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200">
                <tr>
                  <th className={th}>Tier</th>
                  <th className={th}>Model</th>
                  <th className={thNum}>Calls</th>
                  <th className={thNum}>Avg in</th>
                  <th className={thNum}>Avg cached</th>
                  <th className={thNum}>Avg out</th>
                  <th className={thNum}>Est. USD</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {est.models.map((m) => (
                  <tr key={`${m.tier}|${m.model}`}>
                    <td className="px-2 py-1">{m.tier}</td>
                    <td className="px-2 py-1">{m.model}</td>
                    <td className={num}>{m.calls}</td>
                    <td className={num}>{m.avg_tokens_in}</td>
                    <td className={num}>{m.avg_tokens_cached}</td>
                    <td className={num}>{m.avg_tokens_out}</td>
                    <td className={num}>
                      {formatUsd(m.est_usd)}
                      {!m.rate_verified && <Unverified />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(est.any_unverified || est.models.some((m) => !m.rate_verified)) && (
            <p className="mt-2 text-xs text-ink-2">{UNVERIFIED_HELP}</p>
          )}
          {est.monthly_remaining_usd != null && (
            <p className="mt-2 text-sm text-ink-2">
              Monthly budget remaining: <span className="tabular-nums">{formatUsd(est.monthly_remaining_usd)}</span>
            </p>
          )}
          {est.project_remaining_usd != null && (
            <p className="mt-1 text-sm text-ink-2">
              Project budget remaining: <span className="tabular-nums">{formatUsd(est.project_remaining_usd)}</span>
            </p>
          )}
          {!est.within_budget && (
            <p role="alert" className="mt-2 rounded-control bg-warning-subtle px-3 py-2 text-sm font-medium text-ink">
              This is over the remaining AI budget. Reading may stop part way.
            </p>
          )}
        </>
      )}
      {est.note && <p className="mt-2 text-sm text-muted">{est.note}</p>}
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={confirm.isPending}
          onClick={onConfirm}
          className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 disabled:opacity-50"
        >
          {internal ? 'Start' : 'Confirm and start'}
        </button>
      </div>
    </Modal>
  )
}
