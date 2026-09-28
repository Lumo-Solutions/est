import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  useBoqRevisions,
  useContractRevisions,
  useContracts,
  useContractVariations,
  useExclusionRegister,
  useOutturnCostObservations,
} from '../features/moduleE/api'

// All read-only, any authenticated role server-side (module_e.py uses
// CurrentUser throughout) -- no write forms, no role gating needed.

function ContractDetail({ contractId }: { contractId: string }) {
  const { data: revisions, isLoading: revLoading } = useContractRevisions(contractId)
  const { data: variations, isLoading: varLoading } = useContractVariations(contractId)

  return (
    <div className="mt-3 rounded border border-slate-200 p-3">
      <h3 className="text-sm font-semibold text-slate-800">Revisions</h3>
      {revLoading && <p className="mt-1 text-sm text-slate-500">Loading...</p>}
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
      {varLoading && <p className="mt-1 text-sm text-slate-500">Loading...</p>}
      {variations && variations.length === 0 && <p className="mt-1 text-sm text-slate-500">No variations.</p>}
      {variations && variations.length > 0 && (
        <table className="mt-1 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-1">Ref</th>
              <th>Description</th>
              <th>Delta amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {variations.map((v) => (
              <tr key={v.id} className="border-b border-slate-100">
                <td className="py-1">{v.variation_ref ?? '--'}</td>
                <td>{v.description}</td>
                <td>{v.delta_amount === null ? '--' : v.delta_amount.toFixed(2)}</td>
                <td>{v.status}</td>
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

  if (isLoading) return <p className="text-slate-500">Loading...</p>
  if (isError) return <p className="text-red-600">{error.message}</p>
  if (!contracts || contracts.length === 0) return <p className="text-slate-500">No contracts awarded yet.</p>

  return (
    <div>
      <ul className="space-y-1 text-sm">
        {contracts.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}
              className="text-slate-800 hover:underline"
            >
              {c.contract_ref ?? c.id} — {c.status}
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
  if (isLoading) return <p className="text-slate-500">Loading...</p>
  if (isError) return <p className="text-red-600">{error.message}</p>
  if (!data || data.length === 0) return <p className="text-slate-500">No BOQ revisions yet.</p>
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
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        className="mb-3 rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All statuses</option>
        <option value="open">Open</option>
        <option value="resolved">Resolved</option>
      </select>
      {isLoading && <p className="text-slate-500">Loading...</p>}
      {isError && <p className="text-red-600">{error.message}</p>}
      {data && data.length === 0 && <p className="text-slate-500">No exclusion register entries.</p>}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-1">Description</th>
              <th>Status</th>
              <th>Resolution note</th>
            </tr>
          </thead>
          <tbody>
            {data.map((e) => (
              <tr key={e.id} className="border-b border-slate-100">
                <td className="py-1">{e.description}</td>
                <td>{e.status}</td>
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
  if (isLoading) return <p className="text-slate-500">Loading...</p>
  if (isError) return <p className="text-red-600">{error.message}</p>
  if (!data || data.length === 0) return <p className="text-slate-500">No outturn cost observations yet.</p>
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-slate-200 text-slate-500">
        <tr>
          <th className="py-1">Observed at</th>
          <th>Unit cost</th>
          <th>Quantity</th>
          <th>Currency</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {data.map((o) => (
          <tr key={o.id} className="border-b border-slate-100">
            <td className="py-1">{o.observed_at}</td>
            <td>{o.observed_unit_cost.toFixed(2)}</td>
            <td>{o.observed_quantity ?? '--'}</td>
            <td>{o.currency}</td>
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
      <nav className="mt-3 flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-t px-3 py-1.5 text-sm ${
              tab.key === activeTab
                ? 'border-b-2 border-slate-800 font-medium text-slate-800'
                : 'text-slate-500 hover:text-slate-700'
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
