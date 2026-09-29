import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCheckDuplicates, useCreateVendor, useVendors } from '../features/vendors/api'
import { Role } from '../lib/roles'
import type { VendorCreate } from '../types/api'
import { PageTitle } from '../components/PageTitle'
import { Table, TableCard, Td, Th } from '../components/Table'

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
      className="mb-6 rounded-card p-5 bg-white"
      onSubmit={(e) => {
        e.preventDefault()
        createVendor.mutate({ data: asPayload() }, { onSuccess: onDone })
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="legal-name">
            Legal name
          </label>
          <input
            id="legal-name"
            required
            value={legalName}
            onChange={(e) => setLegalName(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="trade-license">
            Trade license no.
          </label>
          <input
            id="trade-license"
            value={tradeLicenseNo}
            onChange={(e) => setTradeLicenseNo(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="primary-email">
            Primary email
          </label>
          <input
            id="primary-email"
            type="email"
            value={primaryEmail}
            onChange={(e) => setPrimaryEmail(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <button
          type="button"
          disabled={!legalName || checkDuplicates.isPending}
          onClick={() => checkDuplicates.mutate(asPayload())}
          className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Check for duplicates
        </button>
        <button
          type="submit"
          disabled={createVendor.isPending}
          className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
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
    <div className="px-6 py-6 xl:px-10">
      <div className="mb-4 flex items-center justify-between">
        <PageTitle>Vendors</PageTitle>
        <div className="flex items-center gap-2">
          {hasRole(...WRITE_ROLES) && (
            <Link
              to="/vendors/duplicates"
              className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Review duplicates
            </Link>
          )}
          {hasRole(...WRITE_ROLES) && (
            <button
              type="button"
              onClick={() => setShowForm((v) => !v)}
              className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
          className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
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
      {data && data.items.length === 0 && <p className="text-muted">No vendors yet.</p>}
      {data && data.items.length > 0 && (
        <>
          <TableCard>
            <Table density="comfortable">
              <thead className="border-b border-hairline text-muted">
                <tr>
                  <Th>Legal name</Th>
                  <Th>Trade license</Th>
                  <Th>Emirate</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((v) => (
                  <tr key={v.id} className="border-b border-row-rule hover:bg-canvas">
                    <Td>
                      <Link
                        to={`/vendors/${v.id}`}
                        className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                      >
                        {v.legal_name}
                      </Link>
                    </Td>
                    <Td>{v.trade_license_no ?? '--'}</Td>
                    <Td>{v.emirate ?? '--'}</Td>
                    <Td>
                      <Badge tone={STATUS_TONE[v.status] ?? 'neutral'}>{v.status}</Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableCard>
          <p className="mt-2 text-xs text-muted">
            Showing {data.items.length} of {data.total}
          </p>
        </>
      )}
    </div>
  )
}
