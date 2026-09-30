import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Badge, type BadgeTone } from '../../components/Badge'
import { ConfirmModal } from '../../components/ConfirmModal'
import { SkeletonRows } from '../../components/Skeleton'
import { Role } from '../../lib/roles'
import type { AiCallStatus } from '../../types/api'
import { AiStatusNotice } from '../ai/AiStatusNotice'
import { useAiStatus, useAiUsage, useSetExternalAi } from '../ai/api'
import { useIntakeSettings, useSetIntakeSettings } from './api'

// Mirrors the backend: only the managing director changes the switch;
// bd_director may additionally read usage.
const SWITCH_ROLES = [Role.MANAGING_DIRECTOR]
const USAGE_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

const CALL_STATUS_TONE: Record<AiCallStatus, BadgeTone> = {
  ok: 'success',
  cached: 'info',
  error: 'danger',
  blocked: 'warning',
}

const usd = (n: number) => `$${n.toFixed(2)}`
const th = 'px-2 py-1.5 text-left text-xs font-medium uppercase tracking-wide text-slate-500'
const thNum = 'px-2 py-1.5 text-right text-xs font-medium uppercase tracking-wide text-slate-500'
const num = 'px-2 py-1.5 text-right tabular-nums'

function IntakeAutoAcceptCard({ canEdit }: { canEdit: boolean }) {
  const { data, isLoading, isError, error } = useIntakeSettings()
  const save = useSetIntakeSettings()
  const [draft, setDraft] = useState<string | null>(null)

  const currentPct = data ? Math.round(data.auto_accept_min * 100) : null
  const value = draft ?? (currentPct != null ? String(currentPct) : '')
  const parsed = Number(value)
  const valid = value.trim() !== '' && Number.isInteger(parsed) && parsed >= 50 && parsed <= 100
  const invalid = draft !== null && !valid

  return (
    <section aria-labelledby="intake-auto-accept-title">
      <h2 id="intake-auto-accept-title" className="text-sm font-semibold text-slate-800">
        Tender intake: automatic acceptance
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Files the AI classifies at or above this confidence are accepted and routed automatically: drawings go to
        extraction, BOQ files to ready-to-import, addenda to the register, and everything else to the document
        register. Anything below appears under &quot;Needs your check&quot; on the project page.
      </p>
      {isLoading && <SkeletonRows count={1} />}
      {isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error.message}
        </p>
      )}
      {data && currentPct != null && (
        <>
          <p className="mt-2 text-sm text-slate-600">
            Current value: <span className="tabular-nums font-medium">{currentPct}%</span>
          </p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="intake-auto-accept-min" className="block text-sm text-slate-700">
                Auto-accept at or above (%)
              </label>
              <input
                id="intake-auto-accept-min"
                type="number"
                min={50}
                max={100}
                step={1}
                value={value}
                disabled={!canEdit || save.isPending}
                aria-invalid={invalid}
                aria-describedby={invalid ? 'intake-auto-accept-error' : undefined}
                onChange={(e) => setDraft(e.target.value)}
                className="mt-1 w-28 rounded-control border border-outline px-3 py-1.5 text-sm tabular-nums text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand disabled:bg-canvas"
              />
            </div>
            {canEdit && (
              <button
                type="button"
                disabled={!valid || draft === null || save.isPending}
                onClick={() =>
                  save.mutate({ auto_accept_min: Math.round(parsed) / 100 }, { onSuccess: () => setDraft(null) })
                }
                className="rounded-control bg-brand px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 disabled:opacity-50"
              >
                Save
              </button>
            )}
          </div>
          {invalid && (
            <p id="intake-auto-accept-error" className="mt-1 text-sm text-danger">
              Enter a whole number from 50 to 100.
            </p>
          )}
          {!canEdit && <p className="mt-1 text-xs text-slate-500">Only the managing director can change this</p>}
          {save.isSuccess && draft === null && (
            <p role="status" className="mt-1 text-sm text-success">
              Saved
            </p>
          )}
          {save.isError && (
            <p role="alert" className="mt-1 text-sm text-danger">
              {save.error.message}
            </p>
          )}
        </>
      )}
    </section>
  )
}

export function AiAdmin() {
  const { hasRole } = useAuth()
  const canSwitch = hasRole(...SWITCH_ROLES)
  const canSeeUsage = hasRole(...USAGE_ROLES)
  const { data: status, isLoading, isError, error } = useAiStatus()
  const { data: usage, isLoading: usageLoading, isError: usageError, error: usageErr } = useAiUsage(30, canSeeUsage)
  const setExternal = useSetExternalAi()
  const [confirming, setConfirming] = useState(false)

  if (isLoading) return <SkeletonRows count={3} />
  if (isError)
    return (
      <p role="alert" className="text-sm text-danger">
        {error.message}
      </p>
    )
  if (!status) return null

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-semibold text-slate-800">External AI</h2>
        <p className="mt-2 text-sm text-slate-600">
          Provider: <span className="font-medium">{status.provider}</span>{' '}
          <Badge tone={status.configured ? 'success' : 'warning'}>
            {status.configured ? 'Configured' : 'Not configured'}
          </Badge>{' '}
          {status.external && <Badge tone="info">External</Badge>}
        </p>
        <div className="mt-2">
          <AiStatusNotice />
        </div>
        <div className="mt-3 flex items-center gap-2">
          <input
            id="ai-external-allowed"
            type="checkbox"
            role="switch"
            checked={status.external_ai_allowed}
            disabled={!canSwitch || setExternal.isPending}
            onChange={() => setConfirming(true)}
            className="h-4 w-4 rounded border-slate-300 text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          />
          <label htmlFor="ai-external-allowed" className="text-sm text-slate-700">
            External AI allowed
          </label>
        </div>
        {!canSwitch && (
          <p className="mt-1 text-xs text-slate-500">Only the managing director can change this setting.</p>
        )}
        {setExternal.isError && (
          <p role="alert" className="mt-1 text-sm text-danger">
            {setExternal.error.message}
          </p>
        )}
        <ConfirmModal
          open={confirming}
          title={status.external_ai_allowed ? 'Turn off external AI?' : 'Allow external AI?'}
          message={
            status.external_ai_allowed
              ? 'AI features that need an external provider will stop working for this organisation.'
              : 'Tenant documents will be sent to the configured external AI provider to power AI features. Individual projects can still opt out.'
          }
          confirmLabel={status.external_ai_allowed ? 'Turn off' : 'Allow'}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setExternal.mutate(!status.external_ai_allowed)
            setConfirming(false)
          }}
        />
      </section>

      <IntakeAutoAcceptCard canEdit={canSwitch} />

      {!canSeeUsage && <p className="text-xs text-slate-500">Your role cannot view AI usage.</p>}
      {canSeeUsage && usageLoading && <SkeletonRows count={3} />}
      {canSeeUsage && usageError && (
        <p role="alert" className="text-sm text-danger">
          {usageErr.message}
        </p>
      )}
      {usage && (
        <>
          <section>
            <h2 className="text-sm font-semibold text-slate-800">Spend this month</h2>
            <p className="mt-2 text-sm text-slate-600">
              <span className="tabular-nums font-medium">{usd(usage.month_to_date_usd)}</span>
              {usage.monthly_budget_usd != null && (
                <> of <span className="tabular-nums">{usd(usage.monthly_budget_usd)}</span> monthly budget</>
              )}
              {usage.project_budget_usd != null && (
                <> · <span className="tabular-nums">{usd(usage.project_budget_usd)}</span> per-project budget</>
              )}
            </p>
          </section>

          <section>
            <h2 className="text-sm font-semibold text-slate-800">Usage (last 30 days)</h2>
            {usage.rows.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">No AI calls recorded.</p>
            ) : (
              <table className="mt-2 w-full text-sm">
                <thead className="border-b border-slate-200">
                  <tr>
                    <th className={th}>Task</th>
                    <th className={th}>Provider</th>
                    <th className={th}>Model</th>
                    <th className={thNum}>Calls</th>
                    <th className={thNum}>Cached</th>
                    <th className={thNum}>Errors</th>
                    <th className={thNum}>Blocked</th>
                    <th className={thNum}>Tokens in</th>
                    <th className={thNum}>Tokens out</th>
                    <th className={thNum}>Cost (USD)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {usage.rows.map((r) => (
                    <tr key={`${r.task}|${r.provider}|${r.model}`}>
                      <td className="px-2 py-1.5">{r.task}</td>
                      <td className="px-2 py-1.5">{r.provider}</td>
                      <td className="px-2 py-1.5">{r.model}</td>
                      <td className={num}>{r.calls}</td>
                      <td className={num}>{r.cached}</td>
                      <td className={num}>{r.errors}</td>
                      <td className={num}>{r.blocked}</td>
                      <td className={num}>{r.tokens_in}</td>
                      <td className={num}>{r.tokens_out}</td>
                      <td className={num}>{usd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2 className="text-sm font-semibold text-slate-800">Recent calls</h2>
            {usage.recent.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">No recent calls.</p>
            ) : (
              <table className="mt-2 w-full text-sm">
                <thead className="border-b border-slate-200">
                  <tr>
                    <th className={th}>When</th>
                    <th className={th}>Task</th>
                    <th className={th}>Model</th>
                    <th className={th}>Status</th>
                    <th className={thNum}>Tokens</th>
                    <th className={thNum}>Cost (USD)</th>
                    <th className={thNum}>Latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {usage.recent.map((c) => (
                    <tr key={c.id}>
                      <td className="px-2 py-1.5 text-slate-600">{new Date(c.created_at).toLocaleString()}</td>
                      <td className="px-2 py-1.5">{c.task}</td>
                      <td className="px-2 py-1.5">{c.model}</td>
                      <td className="px-2 py-1.5">
                        <Badge tone={CALL_STATUS_TONE[c.status] ?? 'neutral'}>{c.status}</Badge>
                        {c.error && <span className="ml-2 text-xs text-slate-500">{c.error}</span>}
                      </td>
                      <td className={num}>{c.tokens_in + c.tokens_out}</td>
                      <td className={num}>{usd(c.cost_usd)}</td>
                      <td className={num}>{c.latency_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  )
}
