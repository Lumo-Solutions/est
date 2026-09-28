import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import { useReplaceVendorServiceRegions, useVendorServiceRegions, useVendorsPage } from './api'

const EMIRATES = ['Abu Dhabi', 'Dubai', 'Sharjah', 'Ajman', 'Umm Al Quwain', 'Ras Al Khaimah', 'Fujairah']

// Mirrors backend/app/api/v1/routes/vendors.py's _WRITE_ROLES.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

export function VendorRegionsAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: vendorPage } = useVendorsPage(200)
  const [vendorId, setVendorId] = useState('')
  const { data: regions } = useVendorServiceRegions(vendorId || undefined)
  const replace = useReplaceVendorServiceRegions(vendorId || undefined)
  const [selected, setSelected] = useState<string[]>([])

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Vendor service regions</h2>
      <label htmlFor="vendor-regions-vendor" className="sr-only">
        Vendor
      </label>
      <select
        id="vendor-regions-vendor"
        value={vendorId}
        onChange={(e) => {
          setVendorId(e.target.value)
          setSelected([])
        }}
        className="mt-2 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      >
        <option value="">-- Vendor --</option>
        {(vendorPage?.items ?? []).map((v) => (
          <option key={v.id} value={v.id}>{v.legal_name}</option>
        ))}
      </select>

      {vendorId && regions && (
        <div className="mt-2">
          <div className="flex flex-wrap gap-2">
            {EMIRATES.map((emirate) => {
              const checked = (selected.length > 0 ? selected : regions).includes(emirate)
              return (
                <label key={emirate} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!canWrite}
                    onChange={(e) => {
                      const base = selected.length > 0 ? selected : regions
                      setSelected(e.target.checked ? [...base, emirate] : base.filter((r) => r !== emirate))
                    }}
                    className="accent-brand"
                  />
                  {emirate}
                </label>
              )
            })}
          </div>
          {canWrite ? (
            <button
              type="button"
              onClick={() => replace.mutate(selected.length > 0 ? selected : regions)}
              disabled={replace.isPending}
              className="mt-2 rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Save regions
            </button>
          ) : (
            <p className="mt-2 text-xs text-slate-500">Your role can view service regions but not change them.</p>
          )}
          {replace.isError && (
            <p role="alert" className="mt-1 text-sm text-danger">
              {replace.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
