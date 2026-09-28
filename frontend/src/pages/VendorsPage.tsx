import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCheckDuplicates, useCreateVendor, useVendors } from '../features/vendors/api'
import { Role } from '../lib/roles'
import type { VendorCreate } from '../types/api'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// VendorStatus (draft/active/on_hold/blacklisted/merged).
const STATUS_TONE: Record<string, BadgeTone> = {
  draft: 'warning',
  active: 'success',
  on_hold: 'warning',
  blacklisted: 'danger',
  merged: 'neutral',
}

function NewVendorForm({ onDone }: { onDone: () => void }) {
  const [legalName, setLegalName] = useState('')
  const [tradeLicenseNo, setTradeLicenseNo] = useState('')
  const [primaryEmail, setPrimaryEmail] = useState('')
  const createVendor = useCreateVendor()
  const checkDuplicates = useCheckDuplicates()

  const asPayload = (): VendorCreate => ({
    legal_name: legalName,
    trade_license_no: tradeLicenseNo || null,
    primary_email: primaryEmail || null,
  })

  return (
    <form
      className="mb-6 rounded border border-slate-200 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        createVendor.mutate({ data: asPayload() }, { onSuccess: onDone })
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-slate-500" htmlFor="legal-name">
            Legal name
          </label>
          <input
            id="legal-name"
            required
            value={legalName}
            onChange={(e) => setLegalName(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="trade-license">
            Trade license no.
          </label>
          <input
            id="trade-license"
            value={tradeLicenseNo}
            onChange={(e) => setTradeLicenseNo(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="primary-email">
            Primary email
          </label>
          <input
            id="primary-email"
            type="email"
            value={primaryEmail}
            onChange={(e) => setPrimaryEmail(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <button
          type="button"
          disabled={!legalName || checkDuplicates.isPending}
          onClick={() => checkDuplicates.mutate(asPayload())}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Check for duplicates
        </button>
        <button
          type="submit"
          disabled={createVendor.isPending}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
        >
          Create vendor
        </button>
      </div>
      {checkDuplicates.isSuccess && (
        <div className="mt-2 text-sm">
          {checkDuplicates.data.candidates.length === 0 ? (
            <p className="text-emerald-700">No likely duplicates found.</p>
          ) : (
            <div className="rounded border border-amber-300 bg-warning-subtle p-2 text-amber-800">
              <p className="font-medium">Possible duplicates (highest match {Math.round(checkDuplicates.data.highest_score * 100)}%):</p>
              <ul className="mt-1 list-disc pl-4">
                {checkDuplicates.data.candidates.map((c) => (
                  <li key={c.existing_vendor_id}>
                    {c.existing_vendor_name} — {Math.round(c.score * 100)}% match
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {checkDuplicates.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {checkDuplicates.error.message}
        </p>
      )}
      {createVendor.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {createVendor.error.message}
        </p>
      )}
    </form>
  )
}

export function VendorsPage() {
  const { hasRole } = useAuth()
  const [showForm, setShowForm] = useState(false)
  const [status, setStatus] = useState('')
  const { data, isLoading, isError, error } = useVendors({ status: status || undefined })

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Vendors</h1>
        <div className="flex items-center gap-2">
          {hasRole(...WRITE_ROLES) && (
            <Link
              to="/vendors/duplicates"
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Review duplicates
            </Link>
          )}
          {hasRole(...WRITE_ROLES) && (
            <button
              type="button"
              onClick={() => setShowForm((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              {showForm ? 'Cancel' : 'New vendor'}
            </button>
          )}
        </div>
      </div>
      {showForm && <NewVendorForm onDone={() => setShowForm(false)} />}
      <div className="mb-3">
        <label htmlFor="vendor-status-filter" className="sr-only">
          Filter by status
        </label>
        <select
          id="vendor-status-filter"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        >
          {/* Options match backend/app/core/enums.py's VendorStatus exactly
              -- "Suspended" (not a real status) silently returned zero rows
              before this fix, since the server has on_hold/blacklisted/
              merged instead. */}
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="active">Active</option>
          <option value="on_hold">On hold</option>
          <option value="blacklisted">Blacklisted</option>
          <option value="merged">Merged</option>
        </select>
      </div>
      {isLoading && <SkeletonRows count={6} />}
      {isError && (
        <p role="alert" className="text-danger">
          {error.message}
        </p>
      )}
      {data && data.items.length === 0 && <p className="text-slate-500">No vendors yet.</p>}
      {data && data.items.length > 0 && (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2 font-medium">Legal name</th>
                <th className="font-medium">Trade license</th>
                <th className="font-medium">Emirate</th>
                <th className="font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((v) => (
                <tr key={v.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2">
                    <Link
                      to={`/vendors/${v.id}`}
                      className="rounded text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      {v.legal_name}
                    </Link>
                  </td>
                  <td>{v.trade_license_no ?? '--'}</td>
                  <td>{v.emirate ?? '--'}</td>
                  <td>
                    <Badge tone={STATUS_TONE[v.status] ?? 'neutral'}>{v.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">
            Showing {data.items.length} of {data.total}
          </p>
        </>
      )}
    </div>
  )
}
