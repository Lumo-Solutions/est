import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { Spinner } from '../components/Spinner'
import { TextPromptModal } from '../components/TextPromptModal'
import { useTaxonomyNodes } from '../features/admin/api'
import { AgentSourceBadge } from '../features/agentLines/AgentBadges'
import { AgentConfidenceAndFlags } from '../features/agentLines/AgentConfidenceAndFlags'
import { AgentLineDrawer } from '../features/agentLines/AgentLineDrawer'
import { AgentSummaryBar } from '../features/agentLines/AgentSummaryBar'
import { useAgentLines, useAgentSummary, useRefreshAgent } from '../features/agentLines/api'
import { AGENT_ACTION_ROLES, lineDomId } from '../features/agentLines/constants'
import { unconfirmedText } from '../features/agentLines/text'
import type { AgentLine } from '../features/agentLines/types'
import { ApiError } from '../lib/api'
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
import { useProjectAddenda } from '../features/tenderIntake/api'
import { useCurrentSettlement } from '../features/settlement/useCurrentSettlement'
import { AiCostProposalsPanel } from '../features/settlementAi/AiCostProposalsPanel'
import { MarkupAdvicePanel } from '../features/settlementAi/MarkupAdvicePanel'
import { formatMarginPct, formatMoney } from '../lib/format'
import { Role } from '../lib/roles'
import type { BidSettlementLineItemOut, BidSettlementOut, BidSettlementTradeOverrideOut, SimulateRequest, SimulateResult } from '../types/api'
import { PageTitle } from '../components/PageTitle'

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// BidSettlementStatus (draft/submitted/approved/rejected/won/lost).
const SETTLEMENT_STATUS_TONE: Record<string, BadgeTone> = {
  draft: 'warning',
  submitted: 'info',
  approved: 'success',
  rejected: 'danger',
  won: 'success',
  lost: 'danger',
}

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
    <div className="mt-4 border-t border-hairline pt-4">
      <h3 className="text-lg font-semibold text-ink-title">Per-trade overrides</h3>
      <p className="mt-1 text-xs text-muted">
        Away from the project defaults above, for one trade at a time. Leave a field blank to keep whatever override
        already exists for that trade (or the project default, if none).
      </p>
      {tradeOverrides.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {tradeOverrides.map((o) => {
            const tradeName = tradeNodes?.find((t) => t.id === o.trade_node_id)?.name ?? o.trade_node_id
            return (
              <li key={o.id} className="rounded border border-hairline px-2 py-1">
                <span className="font-medium">{tradeName}</span>{' '}
                {PCT_FIELDS.map(({ key, label }) => {
                  const value = o[key as keyof BidSettlementTradeOverrideOut] as number | null
                  return (
                    <span key={key} className="ml-2 text-xs text-ink-2">
                      {label}: <span className="tabular-nums">{value != null ? `${value}%` : 'default'}</span>
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
          aria-label="Trade"
          value={newTradeNodeId}
          onChange={(e) => setNewTradeNodeId(e.target.value)}
          className="rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
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
            aria-label={label}
            placeholder={label}
            value={newValues[key] ?? ''}
            onChange={(e) => setNewValues((v) => ({ ...v, [key]: e.target.value }))}
            className="w-24 rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        ))}
        <button
          type="submit"
          disabled={!newTradeNodeId || setOverride.isPending}
          className="inline-flex items-center gap-1.5 rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {setOverride.isPending && <Spinner />}
          Set override
        </button>
      </form>
      {setOverride.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {setOverride.error.message}
        </p>
      )}
    </div>
  )
}

function LineOverrideRow({
  projectId,
  settlementId,
  currency,
  line,
  agentLine,
  onOpenAgent,
  replaceRequest,
}: {
  projectId: string
  settlementId: string
  currency: string
  line: BidSettlementLineItemOut
  agentLine?: AgentLine
  onOpenAgent?: (lineId: string) => void
  /** Changes when the evidence drawer's Replace is pressed: opens this row's cost entry. */
  replaceRequest?: number
}) {
  const { hasRole } = useAuth()
  const updateLine = useUpdateSettlementLine(projectId, settlementId)
  const setFxRate = useSetLineFxRate(projectId, settlementId)
  const [editing, setEditing] = useState(false)
  const [manualCost, setManualCost] = useState('')
  const [manualCostNote, setManualCostNote] = useState('')
  const [fxRate, setFxRateInput] = useState('')

  // Replace in the evidence drawer opens this row's cost entry (adjusting state while rendering, not in an effect).
  const [seenReplace, setSeenReplace] = useState(replaceRequest)
  if (replaceRequest !== seenReplace) {
    setSeenReplace(replaceRequest)
    if (replaceRequest) setEditing(true)
  }
  useEffect(() => {
    if (replaceRequest && editing) document.getElementById(`manual-${line.id}`)?.focus()
  }, [replaceRequest, editing, line.id])

  return (
    <li
      id={lineDomId(line.id)}
      tabIndex={-1}
      className="rounded border border-hairline px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      <div className="flex items-center justify-between">
        <span>
          Line {line.id.slice(0, 8)} -- qty <span className="tabular-nums">{line.quantity}</span> -- sell rate{' '}
          <span className="tabular-nums">{line.unit_sell_rate != null ? formatMoney(line.unit_sell_rate, currency) : '--'}</span> --
          amount <span className="tabular-nums">{line.line_amount != null ? formatMoney(line.line_amount, currency) : '--'}</span>
        </span>
        {hasRole(...LINE_OVERRIDE_ROLES) && (
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="rounded text-xs text-ink-2 underline transition-colors duration-150 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {editing ? 'Close' : 'Override'}
          </button>
        )}
      </div>
      {agentLine && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <AgentSourceBadge line={agentLine} onOpen={onOpenAgent} />
          <AgentConfidenceAndFlags proposal={agentLine.proposal} />
        </div>
      )}
      {editing && (
        <div className="mt-2 flex flex-wrap items-end gap-2 border-t border-row-rule pt-2">
          <div>
            <label className="mb-1 block text-sm text-ink" htmlFor={`manual-${line.id}`}>
              Manual unit cost
            </label>
            <input
              id={`manual-${line.id}`}
              placeholder={line.direct_unit_cost != null ? String(line.direct_unit_cost) : ''}
              value={manualCost}
              onChange={(e) => setManualCost(e.target.value)}
              className="w-32 rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-ink" htmlFor={`manual-note-${line.id}`}>
              Why (required)
            </label>
            <input
              id={`manual-note-${line.id}`}
              placeholder="e.g. no accepted quote yet, budget estimate"
              value={manualCostNote}
              onChange={(e) => setManualCostNote(e.target.value)}
              className="w-48 rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
            />
          </div>
          <button
            type="button"
            disabled={!manualCost || !manualCostNote.trim() || updateLine.isPending}
            onClick={() =>
              updateLine.mutate(
                {
                  lineId: line.id,
                  data: { cost_source: 'manual', manual_unit_cost: Number(manualCost), source_note: manualCostNote.trim() },
                },
                { onSuccess: () => { setManualCost(''); setManualCostNote('') } },
              )
            }
            className="inline-flex items-center gap-1 rounded-pill border border-brand px-2 py-1 text-xs text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {updateLine.isPending && <Spinner className="h-3 w-3" />}
            Set cost
          </button>
          {hasRole(...LINE_FX_RATE_ROLES) && (
            <>
              <div>
                <label className="mb-1 block text-sm text-ink" htmlFor={`fx-${line.id}`}>
                  FX rate (to {'>'} base)
                </label>
                <input
                  id={`fx-${line.id}`}
                  placeholder={line.fx_rate != null ? String(line.fx_rate) : '1.0'}
                  value={fxRate}
                  onChange={(e) => setFxRateInput(e.target.value)}
                  className="w-24 rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
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
                className="inline-flex items-center gap-1 rounded-pill border border-brand px-2 py-1 text-xs text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {setFxRate.isPending && <Spinner className="h-3 w-3" />}
                Set FX rate
              </button>
            </>
          )}
          {updateLine.isError && (
            <p role="alert" className="w-full text-xs text-danger">
              {updateLine.error.message}
            </p>
          )}
          {setFxRate.isError && (
            <p role="alert" className="w-full text-xs text-danger">
              {setFxRate.error.message}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

function LineOverridesPanel({
  projectId,
  settlementId,
  currency,
  lines,
  agentByLine,
  reviewOnly,
  focusRequest,
  replaceRequest,
  onOpenAgent,
}: {
  projectId: string
  settlementId: string
  currency: string
  lines: BidSettlementLineItemOut[]
  agentByLine: ReadonlyMap<string, AgentLine>
  reviewOnly: boolean
  focusRequest: { lineId: string; n: number } | null
  replaceRequest: { lineId: string; n: number } | null
  onOpenAgent: (lineId: string) => void
}) {
  const { hasRole } = useAuth()
  const shown = reviewOnly ? lines.filter((l) => agentByLine.has(l.id) && !agentByLine.get(l.id)?.agent_confirmed_by) : lines

  useEffect(() => {
    if (!focusRequest) return
    const el = document.getElementById(lineDomId(focusRequest.lineId))
    el?.scrollIntoView?.({ block: 'center' })
    el?.focus()
  }, [focusRequest, shown.length])

  if (!hasRole(...LINE_OVERRIDE_ROLES) || lines.length === 0) return null

  return (
    <div className="mt-4 border-t border-hairline pt-4">
      <h3 className="text-lg font-semibold text-ink-title">Per-line overrides</h3>
      {reviewOnly && <p className="mt-1 text-xs text-muted">Showing only the agent lines that still need confirmation.</p>}
      {reviewOnly && shown.length === 0 && <p className="mt-2 text-sm text-ink-2">No agent lines are waiting for confirmation.</p>}
      <ul className="mt-2 space-y-1">
        {shown.map((line) => (
          <LineOverrideRow
            key={line.id}
            projectId={projectId}
            settlementId={settlementId}
            currency={currency}
            line={line}
            agentLine={agentByLine.get(line.id)}
            onOpenAgent={onOpenAgent}
            replaceRequest={replaceRequest?.lineId === line.id ? replaceRequest.n : undefined}
          />
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
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="ml-2 rounded text-xs text-danger underline transition-colors duration-150 hover:text-red-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
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
        className="rounded text-red-700 underline transition-colors duration-150 hover:text-red-800 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        Confirm delete?
      </button>{' '}
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="rounded text-muted underline transition-colors duration-150 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        Cancel
      </button>
      {deleteScenario.isError && (
        <span role="alert" className="ml-1 text-danger">
          {deleteScenario.error.message}
        </span>
      )}
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
    <div className="border-t border-hairline p-4">
      <h3 className="text-lg font-semibold text-ink-title">Live simulation</h3>
      <div className="mt-2 grid grid-cols-2 gap-4">
        {SLIDERS.map(({ key, label }) => (
          <div key={key}>
            <label className="mb-1 block text-sm text-ink" htmlFor={key}>
              {label}: <span className="tabular-nums">{values[key].toFixed(1)}%</span>
            </label>
            <input
              id={key}
              type="range"
              min={0}
              max={50}
              step={0.1}
              value={values[key]}
              onChange={(e) => onSlide(key, Number(e.target.value))}
              className="w-full accent-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            />
          </div>
        ))}
      </div>

      {result && (
        <div className="mt-3 rounded-card p-5 text-sm bg-white">
          <p className="tabular-nums">
            Tender total: <span className="font-semibold">{formatMoney(result.tender_total, settlement.currency)}</span>
          </p>
          <p className="tabular-nums text-xs text-muted">
            Direct cost {formatMoney(result.direct_cost_total, settlement.currency)} + plant{' '}
            {formatMoney(result.plant_total, settlement.currency)} + overhead {formatMoney(result.overhead_total, settlement.currency)} +
            volatility {formatMoney(result.volatility_total, settlement.currency)} + markup{' '}
            {formatMoney(result.markup_total, settlement.currency)}
          </p>
          {result.margin_on_sell_pct != null && (
            // 3dp, not 2 -- this is the exact value app/services/approvals.py
            // routes on (Decimal end to end, no rounding to the 2dp a
            // sell-total display would use), so a value like 7.995% that
            // escalates to managing_director must not be shown as a
            // rounded "8.00%" that looks like it should stay at
            // bd_director. See docs/build-log.md's Phase 10 section.
            <p className="tabular-nums text-xs text-muted">Margin on sell: {formatMarginPct(result.margin_on_sell_pct)}%</p>
          )}
          {result.required_role && (
            <p className="mt-1 text-xs font-medium text-amber-800">Requires approval by: {result.required_role}</p>
          )}
          {result.unresolved_line_ids.length > 0 && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {result.unresolved_line_ids.length} line(s) unresolved
            </p>
          )}
        </div>
      )}

      <div className="mt-3 flex items-end gap-2">
        <div>
          <label htmlFor="scenario-label" className="sr-only">
            Scenario label
          </label>
          <input
            id="scenario-label"
            placeholder="Scenario label"
            value={scenarioLabel}
            onChange={(e) => setScenarioLabel(e.target.value)}
            className="rounded-lg border border-outline px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <button
          type="button"
          disabled={!scenarioLabel || saveScenario.isPending}
          onClick={() =>
            saveScenario.mutate({ label: scenarioLabel, inputs: values as SimulateRequest }, { onSuccess: () => setScenarioLabel('') })
          }
          className="inline-flex items-center gap-1.5 rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {saveScenario.isPending && <Spinner />}
          Save scenario
        </button>
      </div>
      {saveScenario.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {saveScenario.error.message}
        </p>
      )}
      {scenarios && scenarios.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-ink-2">
          {scenarios.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => {
                  const inputs = s.inputs as Record<string, number>
                  setValues(inputs)
                  runSimulate(inputs)
                }}
                className="rounded underline transition-colors duration-150 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {s.label}
              </button>{' '}
              -- tender total{' '}
              <span className="tabular-nums">
                {s.result.tender_total != null ? formatMoney(s.result.tender_total, settlement.currency) : '--'}
              </span>
              <ScenarioDeleteButton settlementId={settlement.id} scenarioId={s.id} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SubmitApprove({
  projectId,
  settlement,
  unconfirmed,
  onUnconfirmedLines,
}: {
  projectId: string
  settlement: BidSettlementOut
  unconfirmed: number
  onUnconfirmedLines: (lineIds: string[]) => void
}) {
  const { user, hasRole } = useAuth()
  const submit = useSubmitSettlement(projectId, settlement.id)
  const decide = useDecideSettlement(projectId, settlement.id)
  const isSubmitter = user?.sub === settlement.submitted_by
  const [rejectPromptOpen, setRejectPromptOpen] = useState(false)

  // docs/ui-design-system.md section 4.11: the step-up redirect itself is
  // unchanged (lib/api.ts's request() still fires window.location.href to
  // Keycloak the instant a 403 urn:installtec:step-up-required comes back --
  // nothing here alters whether/when that happens). This only adds a brief
  // inline "Verifying..." notice for the moment between the click and the
  // browser actually navigating away, so that moment isn't a silent gap --
  // distinct from decide's other, real error states, which still render as
  // a normal role="alert" message below.
  const stepUpPending = decide.isError && decide.error instanceof ApiError && decide.error.isStepUpRequired

  if (settlement.status === 'draft') {
    if (!hasRole(...SUBMIT_ROLES)) return null
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={() =>
            submit.mutate(undefined, {
              onError: (e) => {
                // 409 + unconfirmed_agent_line_ids: send the person to the first line still unconfirmed.
                const ids = e instanceof ApiError && e.status === 409 ? e.problem.unconfirmed_agent_line_ids : undefined
                if (Array.isArray(ids) && ids.length > 0) onUnconfirmedLines(ids as string[])
              },
            })
          }
          disabled={submit.isPending}
          className="inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {submit.isPending && <Spinner className="text-white" />}
          Submit for approval
        </button>
        {unconfirmed > 0 && <p className="text-xs text-amber-800">{unconfirmedText(unconfirmed)}</p>}
        {submit.isError && (
          <p role="alert" className="text-xs text-danger">
            {submit.error.message}
          </p>
        )}
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
          <span className="text-xs tabular-nums text-muted">Margin on sell: {formatMarginPct(settlement.margin_on_sell_pct)}%</span>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isSubmitter || decide.isPending}
            title={isSubmitter ? 'Segregation of duties: the submitter cannot decide their own request' : ''}
            onClick={() => decide.mutate({ approve: true })}
            className="inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {decide.isPending && <Spinner className="text-white" />}
            Approve
          </button>
          <button
            type="button"
            disabled={isSubmitter || decide.isPending}
            onClick={() => setRejectPromptOpen(true)}
            className="rounded-pill border border-red-700 px-4 py-1.5 text-sm text-red-700 transition-colors duration-150 hover:bg-danger-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Reject
          </button>
          {isSubmitter && <span className="text-xs text-muted">Awaiting a different approver (SoD)</span>}
        </div>
        {stepUpPending ? (
          <p role="status" className="inline-flex items-center gap-1.5 text-xs text-muted">
            <Spinner className="text-muted" />
            Verifying... redirecting you to confirm your identity before this decision can complete.
          </p>
        ) : (
          decide.isError && (
            <p role="alert" className="text-xs text-danger">
              {decide.error.message}
            </p>
          )
        )}
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

  return <p className="text-sm text-muted">Status: {settlement.status}</p>
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
  // Addenda that changed the tender documents after this settlement was built.
  // Only these four roles can open the settlement page, and the addenda
  // endpoint may 403 for anyone else, so do not call it for other roles.
  const { data: addenda } = useProjectAddenda(projectId, { enabled: hasRole(...BUILD_DRAFT_ROLES) })
  const staleAddendum = current ? addenda?.find((a) => a.open_settlement_ids.includes(current.id)) : undefined
  const canAct = hasRole(...AGENT_ACTION_ROLES)
  const { data: agentSummary } = useAgentSummary(current?.id)
  const { data: agentLines } = useAgentLines(current?.id)
  const refreshAgent = useRefreshAgent(current?.id)
  const agentByLine = useMemo(() => new Map((agentLines ?? []).map((l) => [l.line_id, l])), [agentLines])
  const [reviewOnly, setReviewOnly] = useState(false)
  const [openLineId, setOpenLineId] = useState<string | null>(null)
  const [focusRequest, setFocusRequest] = useState<{ lineId: string; n: number } | null>(null)
  const [replaceRequest, setReplaceRequest] = useState<{ lineId: string; n: number } | null>(null)
  const openLine = openLineId ? (agentByLine.get(openLineId) ?? null) : null
  const unconfirmed = current?.status === 'draft' ? (agentSummary?.unconfirmed ?? 0) : 0

  const onReview = () => {
    const next = !reviewOnly
    setReviewOnly(next)
    const first = (agentLines ?? []).find((l) => !l.agent_confirmed_by)?.line_id
    if (next && first) setFocusRequest({ lineId: first, n: Date.now() })
  }
  const onUnconfirmedLines = (ids: string[]) => {
    setReviewOnly(true)
    setFocusRequest({ lineId: ids[0], n: Date.now() })
    void refreshAgent()
  }
  const canBuildNewDraft = (!current || REBUILDABLE_STATUSES.has(current.status)) && hasRole(...BUILD_DRAFT_ROLES)

  return (
    <div className="mx-6 my-6 rounded-card bg-white p-6 xl:mx-10">
      <PageTitle>Settlement cockpit</PageTitle>
      {staleAddendum && current && projectId && (
        <div role="status" className="mt-4 rounded-card bg-warning-subtle px-4 py-3 text-sm text-amber-800">
          {staleAddendum.addendum_no ? `Addendum ${staleAddendum.addendum_no}` : 'An addendum'} changed the tender documents after this settlement was built.{' '}
          {current.status === 'draft' ? 'Refresh quantities before you submit.' : 'Ask for a re-review before deciding.'}{' '}
          <Link
            to={`/projects/${projectId}`}
            className="rounded font-medium underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            View addenda
          </Link>
        </div>
      )}
      {isLoading && <SkeletonRows count={4} />}
      {isError && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error.message}
        </p>
      )}
      {!isLoading && canBuildNewDraft && (
        <button
          type="button"
          onClick={() => buildDraft.mutate()}
          disabled={buildDraft.isPending}
          className="mt-4 inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {buildDraft.isPending && <Spinner className="text-white" />}
          {current ? 'Build new settlement draft' : 'Build settlement draft'}
        </button>
      )}
      {buildDraft.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {buildDraft.error.message}
        </p>
      )}
      {current && projectId && (
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-ink-2">
              <span className="tabular-nums">v{current.version_no}</span>
              <Badge tone={SETTLEMENT_STATUS_TONE[current.status] ?? 'neutral'}>{current.status}</Badge>
              <span>{current.currency}</span>
            </div>
            <div className="flex flex-col items-end gap-1">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => refreshQuantities.mutate()}
                  disabled={refreshQuantities.isPending}
                  className="inline-flex items-center gap-1 rounded text-xs text-ink-2 underline transition-colors duration-150 hover:text-ink disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                >
                  {refreshQuantities.isPending && <Spinner className="h-3 w-3" />}
                  Refresh quantities
                </button>
                <SubmitApprove projectId={projectId} settlement={current} unconfirmed={unconfirmed} onUnconfirmedLines={onUnconfirmedLines} />
              </div>
              {refreshQuantities.isError && (
                <p role="alert" className="text-xs text-danger">
                  {refreshQuantities.error.message}
                </p>
              )}
            </div>
          </div>
          <AgentSummaryBar
            settlementId={current.id}
            summary={agentSummary}
            draft={current.status === 'draft'}
            canAct={canAct}
            reviewing={reviewOnly}
            onReview={onReview}
          />
          {/* key: remount the sliders when the defaults change (e.g. "Use these values") so they show the saved values */}
          <SimulationSliders
            key={`${current.default_plant_pct}-${current.default_overhead_pct}-${current.default_volatility_pct}-${current.default_markup_pct}`}
            settlement={current}
          />
          {current.status === 'draft' && <MarkupAdvicePanel projectId={projectId} settlementId={current.id} currency={current.currency} />}
          {detail && (
            <>
              <TradeOverridesPanel projectId={projectId} settlementId={current.id} tradeOverrides={detail.trade_overrides} />
              {current.status === 'draft' && (
                <AiCostProposalsPanel projectId={projectId} settlementId={current.id} currency={current.currency} />
              )}
              <LineOverridesPanel
                projectId={projectId}
                settlementId={current.id}
                currency={current.currency}
                lines={detail.lines}
                agentByLine={agentByLine}
                reviewOnly={reviewOnly}
                focusRequest={focusRequest}
                replaceRequest={replaceRequest}
                onOpenAgent={setOpenLineId}
              />
            </>
          )}
          <AgentLineDrawer
            line={openLine}
            settlementId={current.id}
            canAct={canAct}
            draft={current.status === 'draft'}
            onClose={() => setOpenLineId(null)}
            onReplace={(lineId) => {
              setOpenLineId(null)
              setReplaceRequest({ lineId, n: Date.now() })
            }}
          />
        </div>
      )}
    </div>
  )
}
