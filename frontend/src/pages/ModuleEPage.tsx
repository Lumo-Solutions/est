import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import {
  useBoqRevisions,
  useContractRevisions,
  useContracts,
  useContractVariations,
  useExclusionRegister,
  useOutturnCostObservations,
} from '../features/moduleE/api'
import { formatMoney } from '../lib/format'

// All read-only, any authenticated role server-side (module_e.py uses
// CurrentUser throughout) -- no write forms, no role gating needed.

// docs/ui-design-system.md section 4.8. Module E's status columns are plain
// `String` columns (backend/app/models/module_e.py), not a StrEnum in
// backend/app/core/enums.py -- there is no write workflow here yet (schema-
// readiness phase, per that file's own module docstring), so the only real
// values observed are each column's server_default plus the one example
// value backend/app/cli.py's demo seeder sets ("active" for a contract).
// Unrecognized values fall back to neutral rather than guessing a tone.
const CONTRACT_STATUS_TONE: Record<string, BadgeTone> = {
  draft: 'warning',
  active: 'success',
  terminated: 'danger',
  closed: 'neutral',
}
const VARIATION_STATUS_TONE: Record<string, BadgeTone> = {
  proposed: 'warning',
  accepted: 'success',
  rejected: 'danger',
}
const EXCLUSION_STATUS_TONE: Record<string, BadgeTone> = {
  open: 'warning',
  resolved: 'success',
}

function ContractDetail({ contractId }: { contractId: string }) {
  const { data: revisions, isLoading: revLoading } = useContractRevisions(contractId)
  const { data: variations, isLoading: varLoading } = useContractVariations(contractId)

  return (
    <div className="mt-3 rounded border border-slate-200 p-3">
      <h3 className="text-sm font-semibold text-slate-800">Revisions</h3>
      {revLoading && <SkeletonRows count={2} />}
      {revisions && revisions.length === 0 && <p className="mt-1 text-sm text-slate-500">No revisions.</p>}
      {revisions && revisions.length > 0 && (
        <ul className="mt-1 space-y-1 text-sm">
          {revisions.map((r) => (
            <li key={r.id}>
              Rev {r.revision_no} — {r.reason ?? 'no reason given'} ({new Date(r.created_at).toLocaleDateString()})
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-3 text-sm font-semibold text-slate-800">Variations</h3>
      {varLoading && <SkeletonRows count={2} />}
      {variations && variations.length === 0 && <p className="mt-1 text-sm text-slate-500">No variations.</p>}
      {variations && variations.length > 0 && (
        <table className="mt-1 w-full text-left text-sm">
          <thead className="border-b border-slate-200 font-medium text-slate-500">
            <tr>
              <th className="py-1">Ref</th>
              <th>Description</th>
              <th className="text-right">Delta amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {variations.map((v) => (
              <tr key={v.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-1">{v.variation_ref ?? '--'}</td>
                <td>{v.description}</td>
                <td className="text-right tabular-nums">{v.delta_amount === null ? '--' : formatMoney(v.delta_amount)}</td>
                <td>
                  <Badge tone={VARIATION_STATUS_TONE[v.status] ?? 'neutral'}>{v.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ContractsTab({ projectId }: { projectId: string }) {
  const { data: contracts, isLoading, isError, error } = useContracts(projectId)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  if (isLoading) return <SkeletonRows count={3} />
  if (isError)
    return (
      <p role="alert" className="text-sm text-danger">
        {error.message}
      </p>
    )
  if (!contracts || contracts.length === 0) return <p className="text-sm text-slate-500">No contracts awarded yet.</p>

  return (
    <div>
      <ul className="space-y-1 text-sm">
        {contracts.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}
              className="flex items-center gap-2 rounded text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              <span>{c.contract_ref ?? c.id}</span>
              <Badge tone={CONTRACT_STATUS_TONE[c.status] ?? 'neutral'}>{c.status}</Badge>
            </button>
          </li>
        ))}
      </ul>
      {selectedId && <ContractDetail contractId={selectedId} />}
    </div>
  )
}

function BoqRevisionsTab({ projectId }: { projectId: string }) {
  const { data, isLoading, isError, error } = useBoqRevisions(projectId)
  if (isLoading) return <SkeletonRows count={3} />
  if (isError)
    return (
      <p role="alert" className="text-sm text-danger">
        {error.message}
      </p>
    )
  if (!data || data.length === 0) return <p className="text-sm text-slate-500">No BOQ revisions yet.</p>
  return (
    <ul className="space-y-1 text-sm">
      {data.map((r) => (
        <li key={r.id}>
          Rev {r.revision_no} — {r.reason ?? 'no reason given'} ({new Date(r.created_at).toLocaleDateString()})
        </li>
      ))}
    </ul>
  )
}

function ExclusionRegisterTab({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState('')
  const { data, isLoading, isError, error } = useExclusionRegister(projectId, status || undefined)
  return (
    <div>
      <label htmlFor="exclusion-status-filter" className="sr-only">
        Filter by status
      </label>
      <select
        id="exclusion-status-filter"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        className="mb-3 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      >
        <option value="">All statuses</option>
        <option value="open">Open</option>
        <option value="resolved">Resolved</option>
      </select>
      {isLoading && <SkeletonRows count={3} />}
      {isError && (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      )}
      {data && data.length === 0 && <p className="text-sm text-slate-500">No exclusion register entries.</p>}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 font-medium text-slate-500">
            <tr>
              <th className="py-1">Description</th>
              <th>Status</th>
              <th>Resolution note</th>
            </tr>
          </thead>
          <tbody>
            {data.map((e) => (
              <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-1">{e.description}</td>
                <td>
                  <Badge tone={EXCLUSION_STATUS_TONE[e.status] ?? 'neutral'}>{e.status}</Badge>
                </td>
                <td>{e.resolution_note ?? '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function OutturnCostsTab({ projectId }: { projectId: string }) {
  const { data, isLoading, isError, error } = useOutturnCostObservations(projectId)
  if (isLoading) return <SkeletonRows count={3} />
  if (isError)
    return (
      <p role="alert" className="text-sm text-danger">
        {error.message}
      </p>
    )
  if (!data || data.length === 0) return <p className="text-sm text-slate-500">No outturn cost observations yet.</p>
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-slate-200 font-medium text-slate-500">
        <tr>
          <th className="py-1">Observed at</th>
          <th className="text-right">Unit cost</th>
          <th className="text-right">Quantity</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {data.map((o) => (
          <tr key={o.id} className="border-b border-slate-100 hover:bg-slate-50">
            <td className="py-1">{o.observed_at}</td>
            <td className="text-right tabular-nums">{formatMoney(o.observed_unit_cost, o.currency)}</td>
            <td className="text-right tabular-nums">{o.observed_quantity ?? '--'}</td>
            <td>{o.source_note ?? '--'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const TABS = [
  { key: 'contracts', label: 'Contracts', Component: ContractsTab },
  { key: 'boq-revisions', label: 'BOQ revisions', Component: BoqRevisionsTab },
  { key: 'exclusion-register', label: 'Exclusion register', Component: ExclusionRegisterTab },
  { key: 'outturn-costs', label: 'Outturn costs', Component: OutturnCostsTab },
] as const

export function ModuleEPage() {
  const { projectId } = useParams()
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]['key']>('contracts')
  const Active = TABS.find((t) => t.key === activeTab)?.Component ?? ContractsTab

  if (!projectId) return null

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Post-award (Module E)</h1>
      {/* docs/ui-design-system.md section 4.5. */}
      <nav className="mt-3 flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
              tab.key === activeTab ? '-mb-px border-b-2 border-brand text-brand' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <div className="mt-4">
        <Active projectId={projectId} />
      </div>
    </div>
  )
}
