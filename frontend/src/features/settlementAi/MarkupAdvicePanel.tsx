import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Badge } from '../../components/Badge'
import { ConfirmModal } from '../../components/ConfirmModal'
import { Spinner } from '../../components/Spinner'
import { AiStatusNotice } from '../ai/AiStatusNotice'
import { useUpdateSettlementDefaults } from '../settlement/api'
import { formatMarginPct, formatMoney } from '../../lib/format'
import type { MarkupAdviceOption } from '../../types/api'
import { useTrackedRun } from './api'
import { AI_RUN_ROLES } from './constants'
import { AiUsageLine, RunProgress, RunWarnings } from './shared'

const BUTTON_SOLID =
  'inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'
const BUTTON_OUTLINE =
  'inline-flex items-center gap-1.5 rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

const OPTION_LABEL: Record<MarkupAdviceOption['label'], string> = {
  competitive: 'Competitive',
  balanced: 'Balanced',
  protective: 'Protective',
}

const pct = (v: number | null | undefined) => (v == null ? '--' : `${v}%`)

export function MarkupAdvicePanel({ projectId, settlementId, currency }: { projectId: string; settlementId: string; currency: string }) {
  const { hasRole } = useAuth()
  const canRun = hasRole(...AI_RUN_ROLES)
  const { run, start, starting, startError } = useTrackedRun(settlementId, 'markup')
  const [useAi, setUseAi] = useState(true)
  const [pending, setPending] = useState<MarkupAdviceOption | null>(null)
  // The existing defaults save the sliders' settlement uses; approval routing
  // and thresholds are enforced by the backend exactly as before.
  const saveDefaults = useUpdateSettlementDefaults(projectId, settlementId)
  const result = run?.status === 'ready' ? run.result : null

  if (!canRun && !result) return null

  return (
    <div className="border-t border-hairline p-4">
      <h3 className="text-lg font-semibold text-ink-title">AI markup advice</h3>
      <p className="mt-1 text-xs text-muted">Suggestions are advice only. You set the values.</p>

      {canRun && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <AiStatusNotice />
          <button type="button" disabled={starting} onClick={() => start(useAi)} className={BUTTON_SOLID}>
            {starting && <Spinner className="text-white" />}
            Suggest markup
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
      <AiUsageLine run={run} />

      {result && (
        <div className="mt-3">
          <div className="grid gap-3 md:grid-cols-3">
            {result.options.map((o) => (
              <section key={o.label} aria-label={`${OPTION_LABEL[o.label]} option`} className="rounded-card border border-hairline p-4 text-sm">
                <h4 className="font-semibold text-ink-title">{OPTION_LABEL[o.label]}</h4>
                <dl className="mt-2 space-y-0.5 tabular-nums">
                  <div>Markup: {o.markup_pct}%</div>
                  <div>Overhead: {o.overhead_pct}%</div>
                  <div>Volatility: {o.volatility_pct}%</div>
                </dl>
                <p className="mt-2 tabular-nums">
                  Tender total: <span className="font-semibold">{formatMoney(Number(o.tender_total), currency)}</span>
                </p>
                <p className="text-xs tabular-nums text-muted">
                  Margin on sell: {o.margin_on_sell_pct != null ? `${formatMarginPct(Number(o.margin_on_sell_pct))}%` : '--'}
                </p>
                <p className="mt-1 text-xs text-muted">Computed by the settlement engine, not the model.</p>
                {o.required_role && <p className="mt-1 text-xs font-medium text-amber-800">Would require approval by: {o.required_role}</p>}
                {o.unresolved_lines > 0 && (
                  <p className="mt-1 text-xs text-danger">
                    <Badge tone="warning">{o.unresolved_lines} unresolved</Badge> line(s) not priced yet
                  </p>
                )}
                <p className="mt-2 text-xs text-ink-2">{o.rationale}</p>
                {canRun && (
                  <button
                    type="button"
                    disabled={saveDefaults.isPending}
                    aria-label={`Use these values: ${OPTION_LABEL[o.label]}`}
                    onClick={() => setPending(o)}
                    className={`mt-3 ${BUTTON_OUTLINE}`}
                  >
                    Use these values
                  </button>
                )}
              </section>
            ))}
          </div>
          {saveDefaults.isSuccess && (
            <p role="status" className="mt-2 text-sm text-emerald-700">
              Defaults updated.
            </p>
          )}
          {saveDefaults.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {saveDefaults.error.message}
            </p>
          )}

          {result.overall && <p className="mt-3 text-sm text-ink-2">{result.overall}</p>}

          {result.per_trade.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="mb-1 text-left font-medium text-ink-title">Suggested range by trade</caption>
                <thead>
                  <tr className="text-xs text-muted">
                    <th scope="col" className="py-1 pr-3 font-medium">Trade</th>
                    <th scope="col" className="py-1 pr-3 font-medium">Markup</th>
                    <th scope="col" className="py-1 pr-3 font-medium">Volatility</th>
                    <th scope="col" className="py-1 font-medium">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {result.per_trade.map((t) => (
                    <tr key={t.trade} className="border-t border-row-rule">
                      <td className="py-1 pr-3">{t.trade}</td>
                      <td className="py-1 pr-3 tabular-nums">{t.markup_low}% to {t.markup_high}%</td>
                      <td className="py-1 pr-3 tabular-nums">
                        {t.volatility_low != null && t.volatility_high != null ? `${t.volatility_low}% to ${t.volatility_high}%` : '--'}
                      </td>
                      <td className="py-1 text-xs text-ink-2">{t.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result.history.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="mb-1 text-left font-medium text-ink-title">Win/loss history by margin</caption>
                <thead>
                  <tr className="text-xs text-muted">
                    <th scope="col" className="py-1 pr-3 font-medium">Margin</th>
                    <th scope="col" className="py-1 pr-3 font-medium">Bids</th>
                    <th scope="col" className="py-1 pr-3 font-medium">Won</th>
                    <th scope="col" className="py-1 pr-3 font-medium">Win rate</th>
                    <th scope="col" className="py-1 font-medium">Avg price gap when lost</th>
                  </tr>
                </thead>
                <tbody>
                  {result.history.map((h) => (
                    <tr key={h.margin_bucket} className="border-t border-row-rule tabular-nums">
                      <td className="py-1 pr-3">{h.margin_bucket}</td>
                      <td className="py-1 pr-3">{h.bids}</td>
                      <td className="py-1 pr-3">{h.won}</td>
                      <td className="py-1 pr-3">{pct(h.win_rate_pct)}</td>
                      <td className="py-1">{pct(h.avg_price_gap_when_lost_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <ConfirmModal
        open={pending != null}
        title="Use these values"
        message={
          pending
            ? `Set the project defaults to markup ${pending.markup_pct}%, overhead ${pending.overhead_pct}%, volatility ${pending.volatility_pct}%. Approval thresholds still apply${pending.required_role ? ` (this would require ${pending.required_role})` : ''}.`
            : undefined
        }
        confirmLabel="Use these values"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (!pending) return
          saveDefaults.mutate({
            default_markup_pct: pending.markup_pct,
            default_overhead_pct: pending.overhead_pct,
            default_volatility_pct: pending.volatility_pct,
          })
          setPending(null)
        }}
      />
    </div>
  )
}
