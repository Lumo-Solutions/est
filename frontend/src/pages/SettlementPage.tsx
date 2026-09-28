import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { TextPromptModal } from '../components/TextPromptModal'
import { useTaxonomyNodes } from '../features/admin/api'
import {
  useBuildSettlementDraft,
  useDecideSettlement,
  useDeleteScenario,
  useRefreshQuantities,
  useSaveScenario,
  useScenarios,
  useSettlement,
  useSetLineFxRate,
  useSetTradeOverride,
  useSimulate,
  useSubmitSettlement,
  useUpdateSettlementLine,
} from '../features/settlement/api'
import { useCurrentSettlement } from '../features/settlement/useCurrentSettlement'
import { formatMarginPct, formatMoney } from '../lib/format'
import { Role } from '../lib/roles'
import type { BidSettlementLineItemOut, BidSettlementOut, BidSettlementTradeOverrideOut, SimulateRequest, SimulateResult } from '../types/api'

// Mirrors backend/app/api/v1/routes/settlement.py's _HEADER_ROLES/_SUBMIT_ROLES:
// building/rebuilding a draft is lead_estimator/procurement_head/bd_director/
// managing_director (notably not estimator); submitting for approval is
// bd_director/managing_director only. Deciding (approve/reject) is NOT a
// static role list -- app/services/approvals.py::decide checks the specific
// routed approval tier's required_role, which BidSettlementOut doesn't
// currently expose -- so that stays ungated here beyond the SoD check below
// (server still enforces it correctly either way; see docs/ui-qa/issues.md).
const BUILD_DRAFT_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
const SUBMIT_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
// Mirrors _LINE_ROLES exactly (same roles that can save a scenario in the
// first place) -- every business role except platform_admin.
const SCENARIO_DELETE_ROLES = [Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
// Mirrors _HEADER_ROLES -- PUT .../trade-overrides/{id} (backend/app/api/v1/
// routes/settlement.py).
const TRADE_OVERRIDE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
// Mirrors _LINE_ROLES -- PATCH .../lines/{id} is open to estimator too,
// unlike the trade-level override above.
const LINE_OVERRIDE_ROLES = [Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
// PATCH .../lines/{id}/fx-rate is _HEADER_ROLES specifically (not
// _LINE_ROLES) -- an estimator can override a line's manual cost but not
// its FX rate.
const LINE_FX_RATE_ROLES = TRADE_OVERRIDE_ROLES

const PCT_FIELDS = [
  { key: 'plant_pct', label: 'Plant %' },
  { key: 'overhead_pct', label: 'Overhead %' },
  { key: 'volatility_pct', label: 'Volatility %' },
  { key: 'markup_pct', label: 'Markup %' },
] as const

function TradeOverridesPanel({ projectId, settlementId, tradeOverrides }: { projectId: string; settlementId: string; tradeOverrides: BidSettlementTradeOverrideOut[] }) {
  const { hasRole } = useAuth()
  const { data: tradeNodes } = useTaxonomyNodes()
  const setOverride = useSetTradeOverride(projectId, settlementId)
  const [newTradeNodeId, setNewTradeNodeId] = useState('')
  const [newValues, setNewValues] = useState<Record<string, string>>({})

  if (!hasRole(...TRADE_OVERRIDE_ROLES)) return null

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-800">Per-trade overrides</h3>
      <p className="mt-1 text-xs text-slate-500">
        Away from the project defaults above, for one trade at a time. Leave a field blank to keep whatever override
        already exists for that trade (or the project default, if none).
      </p>
      {tradeOverrides.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {tradeOverrides.map((o) => {
            const tradeName = tradeNodes?.find((t) => t.id === o.trade_node_id)?.name ?? o.trade_node_id
            return (
              <li key={o.id} className="rounded border border-slate-200 px-2 py-1">
                <span className="font-medium">{tradeName}</span>{' '}
                {PCT_FIELDS.map(({ key, label }) => {
                  const value = o[key as keyof BidSettlementTradeOverrideOut] as number | null
                  return (
                    <span key={key} className="ml-2 text-xs text-slate-600">
                      {label}: {value != null ? `${value}%` : 'default'}
                    </span>
                  )
                })}
              </li>
            )
          })}
        </ul>
      )}
      <form
        className="mt-2 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!newTradeNodeId) return
          const data = Object.fromEntries(
            PCT_FIELDS.map(({ key }) => [key, newValues[key] ? Number(newValues[key]) : null]),
          )
          setOverride.mutate({ tradeNodeId: newTradeNodeId, data }, { onSuccess: () => setNewValues({}) })
        }}
      >
        <select
          value={newTradeNodeId}
          onChange={(e) => setNewTradeNodeId(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">-- Select trade --</option>
          {(tradeNodes ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        {PCT_FIELDS.map(({ key, label }) => (
          <input
            key={key}
            placeholder={label}
            value={newValues[key] ?? ''}
            onChange={(e) => setNewValues((v) => ({ ...v, [key]: e.target.value }))}
            className="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        ))}
        <button
          type="submit"
          disabled={!newTradeNodeId || setOverride.isPending}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Set override
        </button>
      </form>
      {setOverride.isError && <p className="mt-1 text-sm text-red-600">{setOverride.error.message}</p>}
    </div>
  )
}

function LineOverrideRow({ projectId, settlementId, line }: { projectId: string; settlementId: string; line: BidSettlementLineItemOut }) {
  const { hasRole } = useAuth()
  const updateLine = useUpdateSettlementLine(projectId, settlementId)
  const setFxRate = useSetLineFxRate(projectId, settlementId)
  const [editing, setEditing] = useState(false)
  const [manualCost, setManualCost] = useState('')
  const [fxRate, setFxRateInput] = useState('')

  return (
    <li className="rounded border border-slate-200 px-2 py-1 text-sm">
      <div className="flex items-center justify-between">
        <span>
          Line {line.id.slice(0, 8)} -- qty {line.quantity} -- sell rate{' '}
          {line.unit_sell_rate != null ? formatMoney(line.unit_sell_rate) : '--'} -- amount{' '}
          {line.line_amount != null ? formatMoney(line.line_amount) : '--'}
        </span>
        {hasRole(...LINE_OVERRIDE_ROLES) && (
          <button type="button" onClick={() => setEditing((v) => !v)} className="text-xs text-slate-600 underline">
            {editing ? 'Close' : 'Override'}
          </button>
        )}
      </div>
      {editing && (
        <div className="mt-2 flex flex-wrap items-end gap-2 border-t border-slate-100 pt-2">
          <div>
            <label className="block text-xs text-slate-500" htmlFor={`manual-${line.id}`}>
              Manual unit cost
            </label>
            <input
              id={`manual-${line.id}`}
              placeholder={line.direct_unit_cost != null ? String(line.direct_unit_cost) : ''}
              value={manualCost}
              onChange={(e) => setManualCost(e.target.value)}
              className="w-32 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </div>
          <button
            type="button"
            disabled={!manualCost || updateLine.isPending}
            onClick={() =>
              updateLine.mutate(
                { lineId: line.id, data: { cost_source: 'manual', manual_unit_cost: Number(manualCost) } },
                { onSuccess: () => setManualCost('') },
              )
            }
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Set cost
          </button>
          {hasRole(...LINE_FX_RATE_ROLES) && (
            <>
              <div>
                <label className="block text-xs text-slate-500" htmlFor={`fx-${line.id}`}>
                  FX rate (to {'>'} base)
                </label>
                <input
                  id={`fx-${line.id}`}
                  placeholder={line.fx_rate != null ? String(line.fx_rate) : '1.0'}
                  value={fxRate}
                  onChange={(e) => setFxRateInput(e.target.value)}
                  className="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
                />
              </div>
              <button
                type="button"
                disabled={!fxRate || setFxRate.isPending}
                onClick={() =>
                  setFxRate.mutate(
                    { lineId: line.id, data: { fx_rate: Number(fxRate), fx_rate_date: new Date().toISOString().slice(0, 10) } },
                    { onSuccess: () => setFxRateInput('') },
                  )
                }
                className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Set FX rate
              </button>
            </>
          )}
          {updateLine.isError && <p className="w-full text-xs text-red-600">{updateLine.error.message}</p>}
          {setFxRate.isError && <p className="w-full text-xs text-red-600">{setFxRate.error.message}</p>}
        </div>
      )}
    </li>
  )
}

function LineOverridesPanel({ projectId, settlementId, lines }: { projectId: string; settlementId: string; lines: BidSettlementLineItemOut[] }) {
  const { hasRole } = useAuth()
  if (!hasRole(...LINE_OVERRIDE_ROLES) || lines.length === 0) return null

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-800">Per-line overrides</h3>
      <ul className="mt-2 space-y-1">
        {lines.map((line) => (
          <LineOverrideRow key={line.id} projectId={projectId} settlementId={settlementId} line={line} />
        ))}
      </ul>
    </div>
  )
}

function ScenarioDeleteButton({ settlementId, scenarioId }: { settlementId: string; scenarioId: string }) {
  const { hasRole } = useAuth()
  const [confirming, setConfirming] = useState(false)
  const deleteScenario = useDeleteScenario(settlementId)

  if (!hasRole(...SCENARIO_DELETE_ROLES)) return null

  if (!confirming) {
    return (
      <button type="button" onClick={() => setConfirming(true)} className="ml-2 text-xs text-red-600 underline">
        Delete
      </button>
    )
  }
  return (
    <span className="ml-2 text-xs">
      <button
        type="button"
        disabled={deleteScenario.isPending}
        onClick={() => deleteScenario.mutate(scenarioId, { onSettled: () => setConfirming(false) })}
        className="text-red-700 underline disabled:opacity-50"
      >
        Confirm delete?
      </button>{' '}
      <button type="button" onClick={() => setConfirming(false)} className="text-slate-500 underline">
        Cancel
      </button>
      {deleteScenario.isError && <span className="ml-1 text-red-600">{deleteScenario.error.message}</span>}
    </span>
  )
}

const SLIDERS: { key: keyof Pick<SimulateRequest, 'default_plant_pct' | 'default_overhead_pct' | 'default_volatility_pct' | 'default_markup_pct'>; label: string }[] = [
  { key: 'default_plant_pct', label: 'Plant %' },
  { key: 'default_overhead_pct', label: 'Overhead %' },
  { key: 'default_volatility_pct', label: 'Volatility %' },
  { key: 'default_markup_pct', label: 'Markup %' },
]

function SimulationSliders({ settlement }: { settlement: BidSettlementOut }) {
  const [values, setValues] = useState<Record<string, number>>({
    default_plant_pct: settlement.default_plant_pct,
    default_overhead_pct: settlement.default_overhead_pct,
    default_volatility_pct: settlement.default_volatility_pct,
    default_markup_pct: settlement.default_markup_pct,
  })
  const [result, setResult] = useState<SimulateResult | null>(null)
  const [scenarioLabel, setScenarioLabel] = useState('')
  const simulate = useSimulate(settlement.id)
  const saveScenario = useSaveScenario(settlement.id)
  const { data: scenarios } = useScenarios(settlement.id)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runSimulate = (next: Record<string, number>) => {
    simulate.mutate(next as SimulateRequest, { onSuccess: setResult })
  }

  useEffect(() => {
    runSimulate(values)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onSlide = (key: string, value: number) => {
    const next = { ...values, [key]: value }
    setValues(next)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runSimulate(next), 300)
  }

  return (
    <div className="border-t border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Live simulation</h3>
      <div className="mt-2 grid grid-cols-2 gap-4">
        {SLIDERS.map(({ key, label }) => (
          <div key={key}>
            <label className="block text-xs text-slate-500" htmlFor={key}>
              {label}: {values[key].toFixed(1)}%
            </label>
            <input
              id={key}
              type="range"
              min={0}
              max={50}
              step={0.1}
              value={values[key]}
              onChange={(e) => onSlide(key, Number(e.target.value))}
              className="w-full"
            />
          </div>
        ))}
      </div>

      {result && (
        <div className="mt-3 rounded border border-slate-200 p-3 text-sm">
          <p>
            Tender total: <span className="font-semibold">{result.tender_total.toFixed(2)}</span> {settlement.currency}
          </p>
          <p className="text-xs text-slate-500">
            Direct cost {result.direct_cost_total.toFixed(2)} + plant {result.plant_total.toFixed(2)} + overhead{' '}
            {result.overhead_total.toFixed(2)} + volatility {result.volatility_total.toFixed(2)} + markup{' '}
            {result.markup_total.toFixed(2)}
          </p>
          {result.margin_on_sell_pct != null && (
            // 3dp, not 2 -- this is the exact value app/services/approvals.py
            // routes on (Decimal end to end, no rounding to the 2dp a
            // sell-total display would use), so a value like 7.995% that
            // escalates to managing_director must not be shown as a
            // rounded "8.00%" that looks like it should stay at
            // bd_director. See docs/build-log.md's Phase 10 section.
            <p className="text-xs text-slate-500">Margin on sell: {formatMarginPct(result.margin_on_sell_pct)}%</p>
          )}
          {result.required_role && (
            <p className="mt-1 text-xs font-medium text-amber-700">Requires approval by: {result.required_role}</p>
          )}
          {result.unresolved_line_ids.length > 0 && (
            <p className="mt-1 text-xs text-red-600">{result.unresolved_line_ids.length} line(s) unresolved</p>
          )}
        </div>
      )}

      <div className="mt-3 flex items-end gap-2">
        <input
          placeholder="Scenario label"
          value={scenarioLabel}
          onChange={(e) => setScenarioLabel(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <button
          type="button"
          disabled={!scenarioLabel || saveScenario.isPending}
          onClick={() =>
            saveScenario.mutate({ label: scenarioLabel, inputs: values as SimulateRequest }, { onSuccess: () => setScenarioLabel('') })
          }
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Save scenario
        </button>
      </div>
      {scenarios && scenarios.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slate-600">
          {scenarios.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => {
                  const inputs = s.inputs as Record<string, number>
                  setValues(inputs)
                  runSimulate(inputs)
                }}
                className="underline"
              >
                {s.label}
              </button>{' '}
              -- tender total {s.result.tender_total?.toFixed(2)}
              <ScenarioDeleteButton settlementId={settlement.id} scenarioId={s.id} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SubmitApprove({ projectId, settlement }: { projectId: string; settlement: BidSettlementOut }) {
  const { user, hasRole } = useAuth()
  const submit = useSubmitSettlement(projectId, settlement.id)
  const decide = useDecideSettlement(projectId, settlement.id)
  const isSubmitter = user?.sub === settlement.submitted_by
  const [rejectPromptOpen, setRejectPromptOpen] = useState(false)

  if (settlement.status === 'draft') {
    if (!hasRole(...SUBMIT_ROLES)) return null
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={() => submit.mutate()}
          disabled={submit.isPending}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Submit for approval
        </button>
        {submit.isError && <p className="text-xs text-red-600">{submit.error.message}</p>}
      </div>
    )
  }

  // BidSettlementStatus.SUBMITTED (backend/app/core/enums.py) is the
  // string "submitted", not "pending_approval" -- this never matched, so
  // the Approve/Reject controls never rendered for any submitted
  // settlement, for anyone. Pre-existing bug, found while writing a real
  // (non-mocked) Playwright test for the submit -> approve flow -- see
  // docs/build-log.md's Phase 10 section.
  if (settlement.status === 'submitted') {
    return (
      <div className="flex flex-col items-end gap-1">
        {settlement.margin_on_sell_pct != null && (
          // Same 3dp precision as the cockpit's live simulation -- this is
          // the value that actually routed this request, so the approver
          // must see it exactly, not rounded to 2dp.
          <span className="text-xs text-slate-500">Margin on sell: {formatMarginPct(settlement.margin_on_sell_pct)}%</span>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isSubmitter || decide.isPending}
            title={isSubmitter ? 'Segregation of duties: the submitter cannot decide their own request' : ''}
            onClick={() => decide.mutate({ approve: true })}
            className="rounded bg-green-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={isSubmitter || decide.isPending}
            onClick={() => setRejectPromptOpen(true)}
            className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 disabled:opacity-50"
          >
            Reject
          </button>
          {isSubmitter && <span className="text-xs text-slate-500">Awaiting a different approver (SoD)</span>}
        </div>
        {decide.isError && <p className="text-xs text-red-600">{decide.error.message}</p>}
        <TextPromptModal
          open={rejectPromptOpen}
          title="Reject settlement"
          message="Rejection note?"
          submitLabel="Reject"
          onCancel={() => setRejectPromptOpen(false)}
          onSubmit={(note) => {
            decide.mutate({ approve: false, note })
            setRejectPromptOpen(false)
          }}
        />
      </div>
    )
  }

  return <p className="text-sm text-slate-500">Status: {settlement.status}</p>
}

// app/services/settlement.py::build_settlement_draft can always be called
// again -- it just starts version N+1 and demotes whatever was current
// before it, whatever that one's status was (draft.py's docstring: "a
// rejected settlement is never reopened -- the only way forward is a new
// version"). Gating the button on `!current` alone made that documented
// recovery path unreachable from the UI once a project had ever had ONE
// settlement, for its entire remaining lifetime -- these are the statuses
// nothing else in this component still lets you act on, so building fresh
// is the only next step.
const REBUILDABLE_STATUSES = new Set(['approved', 'rejected', 'won', 'lost'])

export function SettlementPage() {
  const { projectId } = useParams()
  const { hasRole } = useAuth()
  const { current, isLoading, isError, error } = useCurrentSettlement(projectId)
  // useCurrentSettlement is built on the list endpoint (GET
  // /projects/{id}/bid-settlements), which never populates lines/
  // trade_overrides (only the single-settlement detail endpoint's
  // _to_out(settlement, lines, trade_overrides) does -- see
  // backend/app/api/v1/routes/settlement.py). The per-trade/per-line
  // override panels need those, so fetch the detail separately once the
  // current settlement's id is known.
  const { data: detail } = useSettlement(current?.id)
  const buildDraft = useBuildSettlementDraft(projectId)
  const refreshQuantities = useRefreshQuantities(projectId, current?.id)
  const canBuildNewDraft = (!current || REBUILDABLE_STATUSES.has(current.status)) && hasRole(...BUILD_DRAFT_ROLES)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Settlement cockpit</h1>
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-red-600">{error.message}</p>}
      {!isLoading && canBuildNewDraft && (
        <button
          type="button"
          onClick={() => buildDraft.mutate()}
          disabled={buildDraft.isPending}
          className="mt-4 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {current ? 'Build new settlement draft' : 'Build settlement draft'}
        </button>
      )}
      {buildDraft.isError && <p className="mt-2 text-sm text-red-600">{buildDraft.error.message}</p>}
      {current && projectId && (
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-600">
              v{current.version_no} -- {current.status} -- {current.currency}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => refreshQuantities.mutate()}
                className="text-xs text-slate-600 underline"
              >
                Refresh quantities
              </button>
              <SubmitApprove projectId={projectId} settlement={current} />
            </div>
          </div>
          <SimulationSliders settlement={current} />
          {detail && (
            <>
              <TradeOverridesPanel projectId={projectId} settlementId={current.id} tradeOverrides={detail.trade_overrides} />
              <LineOverridesPanel projectId={projectId} settlementId={current.id} lines={detail.lines} />
            </>
          )}
        </div>
      )}
    </div>
  )
}
