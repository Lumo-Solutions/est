import { useEffect, useRef } from 'react'
import { Button } from '../../components/Button'
import { formatUsd } from './labels'
import type { AgentEstimate } from './types'

// The cost estimate shown before an external AI provider is used. Nothing has been spent until Confirm.
// Focus moves into the dialog on open, Tab is kept inside, Escape = Cancel, focus returns to where it was.
export function EstimateModal({
  estimate,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  estimate: AgentEstimate | null
  busy: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
    return () => previous?.focus?.()
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onCancel()
      return
    }
    if (e.key !== 'Tab' || !ref.current) return
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'))
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const rows: Array<[string, string]> = estimate
    ? [
        ['Provider', estimate.provider],
        ['Model', estimate.model ?? '-'],
        ['Sections', String(estimate.sections)],
        ['Steps', String(estimate.steps)],
        ['Page views', String(estimate.page_views)],
        ['Estimated cost', formatUsd(estimate.usd)],
        ['Cost cap for this run', formatUsd(estimate.usd_cap)],
      ]
    : []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onCancel}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-estimate-title"
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="max-h-full w-full max-w-md overflow-auto rounded-card bg-white p-6 shadow-lg"
      >
        <h2 id="agent-estimate-title" className="text-lg font-semibold text-ink-title">
          Estimated agent cost
        </h2>
        {estimate ? (
          <>
            <p className="mt-1 text-sm text-muted">
              {estimate.external
                ? 'The agent uses an external AI provider. Nothing is spent until you confirm.'
                : 'The agent uses an internal provider.'}
            </p>
            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
              {rows.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd className="text-right tabular-nums text-ink">{v}</dd>
                </div>
              ))}
            </dl>
            {estimate.unverified_price && (
              <p className="mt-3 rounded bg-warning-subtle px-2 py-1 text-xs text-ink">
                Price not yet verified against your provider invoice.
              </p>
            )}
            {estimate.note && <p className="mt-2 text-xs text-muted">{estimate.note}</p>}
          </>
        ) : (
          <p className="mt-2 text-sm text-muted">No estimate was returned for this run.</p>
        )}
        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onConfirm} loading={busy} data-autofocus="">
            Confirm and start
          </Button>
        </div>
      </div>
    </div>
  )
}
