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
import { PageTitle } from '../components/PageTitle'
import { Table, TableCard, Td, Th } from '../components/Table'
import { TabBar } from '../components/TabBar'

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
    <div className="mt-3 rounded-card p-5 bg-white">
      <h3 className="text-lg font-semibold text-ink-title">Revisions</h3>
      {revLoading && <SkeletonRows count={2} />}
      {revisions && revisions.length === 0 && <p className="mt-1 text-sm text-muted">No revisions.</p>}
      {revisions && revisions.length > 0 && (
        <ul className="mt-1 space-y-1 text-sm">
          {revisions.map((r) => (
            <li key={r.id}>
              Rev {r.revision_no} — {r.reason ?? 'no reason given'} ({new Date(r.created_at).toLocaleDateString()})
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-3 text-lg font-semibold text-ink-title">Variations</h3>
      {varLoading && <SkeletonRows count={2} />}
      {variations && variations.length === 0 && <p className="mt-1 text-sm text-muted">No variations.</p>}
      {variations && variations.length > 0 && (
        <TableCard>
          <Table density="comfortable" className="mt-1">
            <thead className="border-b border-hairline font-medium text-muted">
              <tr>
                <Th>Ref</Th>
                <Th>Description</Th>
                <Th numeric>Delta amount</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {variations.map((v) => (
                <tr key={v.id} className="border-b border-row-rule hover:bg-canvas">
                  <Td>{v.variation_ref ?? '--'}</Td>
                  <Td>{v.description}</Td>
                  <Td numeric className="tabular-nums">{v.delta_amount === null ? '--' : formatMoney(v.delta_amount)}</Td>
                  <Td>
                    <Badge tone={VARIATION_STATUS_TONE[v.status] ?? 'neutral'}>{v.status}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
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
  if (!contracts || contracts.length === 0) return <p className="text-sm text-muted">No contracts awarded yet.</p>

  return (
    <div>
      <ul className="space-y-1 text-sm">
        {contracts.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}
              className="flex items-center gap-2 rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
  if (!data || data.length === 0) return <p className="text-sm text-muted">No BOQ revisions yet.</p>
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
        className="mb-3 rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
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
      {data && data.length === 0 && <p className="text-sm text-muted">No exclusion register entries.</p>}
      {data && data.length > 0 && (
        <TableCard>
          <Table density="comfortable">
            <thead className="border-b border-hairline font-medium text-muted">
              <tr>
                <Th>Description</Th>
                <Th>Status</Th>
                <Th>Resolution note</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id} className="border-b border-row-rule hover:bg-canvas">
                  <Td>{e.description}</Td>
                  <Td>
                    <Badge tone={EXCLUSION_STATUS_TONE[e.status] ?? 'neutral'}>{e.status}</Badge>
                  </Td>
                  <Td>{e.resolution_note ?? '--'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
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
  if (!data || data.length === 0) return <p className="text-sm text-muted">No outturn cost observations yet.</p>
  return (
    <TableCard>
      <Table density="comfortable">
        <thead className="border-b border-hairline font-medium text-muted">
          <tr>
            <Th>Observed at</Th>
            <Th numeric>Unit cost</Th>
            <Th numeric>Quantity</Th>
            <Th>Note</Th>
          </tr>
        </thead>
        <tbody>
          {data.map((o) => (
            <tr key={o.id} className="border-b border-row-rule hover:bg-canvas">
              <Td>{o.observed_at}</Td>
              <Td numeric className="tabular-nums">{formatMoney(o.observed_unit_cost, o.currency)}</Td>
              <Td numeric className="tabular-nums">{o.observed_quantity ?? '--'}</Td>
              <Td>{o.source_note ?? '--'}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </TableCard>
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
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Post-award (Module E)</PageTitle>
      {/* Figma tabs; buttons pattern because costlib-module-e.spec.ts locates
          them by role button. */}
      <div className="mt-2">
        <TabBar
          pattern="buttons"
          label="Post-award sections"
          idPrefix="module-e"
          value={activeTab}
          onChange={(id) => setActiveTab(id as (typeof TABS)[number]['key'])}
          tabs={TABS.map((t) => ({ id: t.key, label: t.label }))}
        />
      </div>
      <div className="mt-6">
        <Active projectId={projectId} />
      </div>
    </div>
  )
}
