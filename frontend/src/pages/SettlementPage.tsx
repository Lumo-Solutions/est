import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  useBuildSettlementDraft,
  useDecideSettlement,
  useRefreshQuantities,
  useSaveScenario,
  useScenarios,
  useSimulate,
  useSubmitSettlement,
} from '../features/settlement/api'
import { useCurrentSettlement } from '../features/settlement/useCurrentSettlement'
import type { BidSettlementOut, SimulateRequest, SimulateResult } from '../types/api'

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
          {result.margin_on_sell_pct != null && <p className="text-xs text-slate-500">Margin on sell: {result.margin_on_sell_pct.toFixed(2)}%</p>}
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
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SubmitApprove({ projectId, settlement }: { projectId: string; settlement: BidSettlementOut }) {
  const { user } = useAuth()
  const submit = useSubmitSettlement(projectId, settlement.id)
  const decide = useDecideSettlement(projectId, settlement.id)
  const isSubmitter = user?.sub === settlement.submitted_by

  if (settlement.status === 'draft') {
    return (
      <button
        type="button"
        onClick={() => submit.mutate()}
        disabled={submit.isPending}
        className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        Submit for approval
      </button>
    )
  }

  if (settlement.status === 'pending_approval') {
    return (
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
          onClick={() => {
            const note = window.prompt('Rejection note?')
            if (note) decide.mutate({ approve: false, note })
          }}
          className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 disabled:opacity-50"
        >
          Reject
        </button>
        {isSubmitter && <span className="text-xs text-slate-500">Awaiting a different approver (SoD)</span>}
      </div>
    )
  }

  return <p className="text-sm text-slate-500">Status: {settlement.status}</p>
}

export function SettlementPage() {
  const { projectId } = useParams()
  const { current, isLoading } = useCurrentSettlement(projectId)
  const buildDraft = useBuildSettlementDraft(projectId)
  const refreshQuantities = useRefreshQuantities(projectId, current?.id)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Settlement cockpit</h1>
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {!isLoading && !current && (
        <button
          type="button"
          onClick={() => buildDraft.mutate()}
          disabled={buildDraft.isPending}
          className="mt-4 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Build settlement draft
        </button>
      )}
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
        </div>
      )}
    </div>
  )
}
