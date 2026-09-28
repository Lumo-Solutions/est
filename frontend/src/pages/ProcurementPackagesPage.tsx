import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { TextPromptModal } from '../components/TextPromptModal'
import { useTaxonomyNodes } from '../features/admin/api'
import { useBoqItems } from '../features/boq/api'
import {
  useAddPackageItems,
  useCreateProcurementPackage,
  useCreateRfqs,
  useDispatchRfq,
  useMatchedVendors,
  usePackageItems,
  useProcurementPackages,
  useResendRfq,
  useRfqs,
} from '../features/procurement/api'
import { Role } from '../lib/roles'

// Mirrors backend/app/api/v1/routes/procurement.py's _STRUCTURE_ROLES --
// creating a package, adding items, and drafting RFQs are all lead/proc/bd/md
// only server-side. An estimator can still reach this page (nav-gated to
// est/lead/proc), so the create form must hide itself rather than let an
// estimator fill it in and hit a silent 403.
const STRUCTURE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

function PackageDetail({ projectId, packageId }: { projectId: string; packageId: string }) {
  const { data: items } = usePackageItems(packageId)
  const { data: allBoqItems } = useBoqItems(projectId)
  const { data: vendors } = useMatchedVendors(packageId)
  const { data: rfqs } = useRfqs(packageId)
  const addItems = useAddPackageItems(packageId)
  const createRfqs = useCreateRfqs(packageId)
  const dispatch = useDispatchRfq(packageId)
  const resend = useResendRfq(packageId)

  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([])
  const [selectedVendorIds, setSelectedVendorIds] = useState<string[]>([])
  const [overrideReason, setOverrideReason] = useState('')
  const [resendTargetId, setResendTargetId] = useState<string | null>(null)

  const linkedIds = new Set((items ?? []).map((i) => i.id))
  const availableItems = (allBoqItems ?? []).filter((i) => !linkedIds.has(i.id))
  const hasIneligibleSelected = (vendors ?? []).some((v) => selectedVendorIds.includes(v.vendor_id) && !v.eligible)

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-800">BOQ items in this package</h3>
      <ul className="mt-1 text-sm text-slate-600">
        {(items ?? []).map((i) => (
          <li key={i.id}>
            {i.item_no}: {i.description}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex items-end gap-2">
        <select
          multiple
          value={selectedItemIds}
          onChange={(e) => setSelectedItemIds(Array.from(e.target.selectedOptions, (o) => o.value))}
          className="h-24 w-64 rounded border border-slate-300 text-sm"
        >
          {availableItems.map((i) => (
            <option key={i.id} value={i.id}>
              {i.item_no}: {i.description}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={selectedItemIds.length === 0 || addItems.isPending}
          onClick={() => addItems.mutate(selectedItemIds, { onSuccess: () => setSelectedItemIds([]) })}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Add items
        </button>
      </div>
      {addItems.isError && <p className="mt-1 text-sm text-red-600">{addItems.error.message}</p>}

      <h3 className="mt-4 text-sm font-semibold text-slate-800">Matched vendors</h3>
      <ul className="mt-1 text-sm">
        {(vendors ?? []).map((v) => (
          <li key={v.vendor_id} className={v.eligible ? 'text-slate-700' : 'text-slate-400'}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selectedVendorIds.includes(v.vendor_id)}
                onChange={(e) =>
                  setSelectedVendorIds((prev) =>
                    e.target.checked ? [...prev, v.vendor_id] : prev.filter((id) => id !== v.vendor_id),
                  )
                }
              />
              {v.legal_name} {!v.eligible && `(ineligible: ${v.ineligible_reason})`}
            </label>
          </li>
        ))}
      </ul>
      {hasIneligibleSelected && (
        <input
          placeholder="Override reason (required for an ineligible vendor)"
          value={overrideReason}
          onChange={(e) => setOverrideReason(e.target.value)}
          className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
      )}
      <button
        type="button"
        disabled={selectedVendorIds.length === 0 || createRfqs.isPending}
        onClick={() =>
          createRfqs.mutate(
            { vendor_ids: selectedVendorIds, override_reason: overrideReason || null },
            { onSuccess: () => setSelectedVendorIds([]) },
          )
        }
        className="mt-2 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        Draft RFQs
      </button>
      {createRfqs.isError && <p className="mt-1 text-sm text-red-600">{createRfqs.error.message}</p>}

      <h3 className="mt-4 text-sm font-semibold text-slate-800">RFQs</h3>
      <table className="mt-1 w-full text-left text-sm">
        <thead className="text-slate-500">
          <tr>
            <th>Ref</th>
            <th>Status</th>
            <th>Dispatch attempts</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(rfqs ?? []).map((rfq) => (
            <tr key={rfq.id}>
              <td>{rfq.rfq_ref ?? rfq.id.slice(0, 8)}</td>
              <td>{rfq.status}</td>
              <td>{rfq.dispatch_attempts}</td>
              <td className="space-x-2">
                <button
                  type="button"
                  disabled={dispatch.isPending}
                  onClick={() => dispatch.mutate(rfq.id)}
                  className="text-slate-600 underline disabled:opacity-50"
                >
                  Dispatch
                </button>
                <button
                  type="button"
                  disabled={resend.isPending}
                  onClick={() => setResendTargetId(rfq.id)}
                  className="text-slate-600 underline disabled:opacity-50"
                >
                  Resend
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {dispatch.isError && <p className="mt-1 text-sm text-red-600">Dispatch failed: {dispatch.error.message}</p>}
      {resend.isError && <p className="mt-1 text-sm text-red-600">Resend failed: {resend.error.message}</p>}
      <TextPromptModal
        open={resendTargetId !== null}
        title="Resend RFQ"
        message="Reason for resending?"
        submitLabel="Resend"
        onCancel={() => setResendTargetId(null)}
        onSubmit={(reason) => {
          if (resendTargetId) resend.mutate({ rfqId: resendTargetId, reason })
          setResendTargetId(null)
        }}
      />
    </div>
  )
}

export function ProcurementPackagesPage() {
  const { projectId } = useParams()
  const { hasRole } = useAuth()
  const { data: packages } = useProcurementPackages(projectId)
  const { data: tradeNodes } = useTaxonomyNodes()
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [tradeNodeId, setTradeNodeId] = useState('')
  const createPackage = useCreateProcurementPackage(projectId)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Procurement packages and RFQs</h1>

      {hasRole(...STRUCTURE_ROLES) && (
        <form
          className="mt-4 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            createPackage.mutate(
              { name, trade_node_id: tradeNodeId || null },
              { onSuccess: () => setName('') },
            )
          }}
        >
          <input
            placeholder="Package name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          {/* Vendor matching (POST /procurement-packages/{id}/matched-vendors)
              requires trade_node_id to be set -- leaving it unset lets you
              create the package but leaves "Matched vendors" permanently
              empty below, with no way to draft an RFQ. */}
          <select
            value={tradeNodeId}
            onChange={(e) => setTradeNodeId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">No trade (vendor matching disabled)</option>
            {(tradeNodes ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <button type="submit" className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white">
            Create package
          </button>
        </form>
      )}
      {createPackage.isError && <p className="mt-1 text-sm text-red-600">{createPackage.error.message}</p>}

      <ul className="mt-4 space-y-1">
        {(packages ?? []).map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => setSelectedPackageId(p.id)}
              className={`w-full rounded px-3 py-2 text-left text-sm ${
                p.id === selectedPackageId ? 'bg-slate-100' : 'hover:bg-slate-50'
              }`}
            >
              {p.name} -- {p.status}
            </button>
          </li>
        ))}
      </ul>

      {selectedPackageId && projectId && <PackageDetail projectId={projectId} packageId={selectedPackageId} />}
    </div>
  )
}
