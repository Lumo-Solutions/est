import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useCheckDuplicates, useCreateVendor, useVendors } from '../features/vendors/api'
import { Role } from '../lib/roles'
import type { VendorCreate } from '../types/api'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <button
          type="button"
          disabled={!legalName || checkDuplicates.isPending}
          onClick={() => checkDuplicates.mutate(asPayload())}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Check for duplicates
        </button>
        <button
          type="submit"
          disabled={createVendor.isPending}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Create vendor
        </button>
      </div>
      {checkDuplicates.isSuccess && (
        <div className="mt-2 text-sm">
          {checkDuplicates.data.candidates.length === 0 ? (
            <p className="text-emerald-700">No likely duplicates found.</p>
          ) : (
            <div className="rounded border border-amber-300 bg-amber-50 p-2 text-amber-800">
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
      {checkDuplicates.isError && <p className="mt-1 text-sm text-red-600">{checkDuplicates.error.message}</p>}
      {createVendor.isError && <p className="mt-1 text-sm text-red-600">{createVendor.error.message}</p>}
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
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              Review duplicates
            </Link>
          )}
          {hasRole(...WRITE_ROLES) && (
            <button
              type="button"
              onClick={() => setShowForm((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              {showForm ? 'Cancel' : 'New vendor'}
            </button>
          )}
        </div>
      </div>
      {showForm && <NewVendorForm onDone={() => setShowForm(false)} />}
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        className="mb-3 rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All statuses</option>
        <option value="draft">Draft</option>
        <option value="active">Active</option>
        <option value="suspended">Suspended</option>
      </select>
      {isLoading && <p className="text-slate-500">Loading...</p>}
      {isError && <p className="text-red-600">{error.message}</p>}
      {data && data.items.length === 0 && <p className="text-slate-500">No vendors yet.</p>}
      {data && data.items.length > 0 && (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2">Legal name</th>
                <th>Trade license</th>
                <th>Emirate</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((v) => (
                <tr key={v.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2">
                    <Link to={`/vendors/${v.id}`} className="text-slate-800 hover:underline">
                      {v.legal_name}
                    </Link>
                  </td>
                  <td>{v.trade_license_no ?? '--'}</td>
                  <td>{v.emirate ?? '--'}</td>
                  <td>{v.status}</td>
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
