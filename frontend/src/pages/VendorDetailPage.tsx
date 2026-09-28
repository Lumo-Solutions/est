import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  useAddCertificate,
  useCertificateTypes,
  useDecidePrequalification,
  useVendorCertificates,
  useVendorPrequalification,
  useVerifyCertificate,
} from '../features/prequal/api'
import { useScanDuplicates, useVendor, useVendorServiceRegions } from '../features/vendors/api'
import { Role } from '../lib/roles'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
// Mirrors backend/app/api/v1/routes/prequal.py's _WRITE_ROLES exactly --
// notably NOT bd_director, unlike vendor master's own write roles above.
const PREQUAL_WRITE_ROLES = [Role.PROCUREMENT_HEAD, Role.LEAD_ESTIMATOR, Role.MANAGING_DIRECTOR]

const EXPIRY_WARNING_DAYS = 30

function expiryBadge(expiryDate: string | null): { label: string; className: string } | null {
  if (!expiryDate) return null
  const days = Math.floor((new Date(expiryDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24))
  if (days < 0) return { label: `Expired ${Math.abs(days)}d ago`, className: 'bg-red-100 text-red-700' }
  if (days <= EXPIRY_WARNING_DAYS) return { label: `Expires in ${days}d`, className: 'bg-amber-100 text-amber-800' }
  return { label: `Valid to ${expiryDate}`, className: 'bg-emerald-100 text-emerald-700' }
}

function CertificatesSection({ vendorId, canWrite }: { vendorId: string; canWrite: boolean }) {
  const { data: certs, isLoading, isError, error } = useVendorCertificates(vendorId)
  const { data: certTypes } = useCertificateTypes()
  const addCertificate = useAddCertificate(vendorId)
  const verifyCertificate = useVerifyCertificate(vendorId)
  const [certTypeId, setCertTypeId] = useState('')
  const [expiryDate, setExpiryDate] = useState('')

  return (
    <div className="mt-6">
      <h2 className="text-sm font-semibold text-slate-800">Certificates</h2>
      {isLoading && <p className="mt-2 text-sm text-slate-500">Loading...</p>}
      {isError && <p className="mt-2 text-sm text-red-600">{error.message}</p>}
      {certs && certs.length === 0 && <p className="mt-2 text-sm text-slate-500">No certificates on file.</p>}
      {certs && certs.length > 0 && (
        <ul className="mt-2 space-y-1">
          {certs.map((c) => {
            const badge = expiryBadge(c.expiry_date)
            return (
              <li key={c.id} className="flex items-center justify-between rounded border border-slate-200 px-2 py-1 text-sm">
                <span>
                  {certTypes?.find((t) => t.id === c.certificate_type_id)?.name ?? c.certificate_type_id}
                  {c.certificate_no ? ` — ${c.certificate_no}` : ''}
                </span>
                <span className="flex items-center gap-2">
                  {badge && <span className={`rounded px-1.5 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>}
                  <span className="text-xs text-slate-500">{c.status}</span>
                  {canWrite && c.status !== 'valid' && (
                    <button
                      type="button"
                      disabled={verifyCertificate.isPending}
                      onClick={() => verifyCertificate.mutate(c.id)}
                      className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      Verify
                    </button>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {verifyCertificate.isError && <p className="mt-1 text-sm text-red-600">{verifyCertificate.error.message}</p>}

      {canWrite && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2 rounded border border-slate-200 p-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!certTypeId) return
            addCertificate.mutate(
              { vendor_id: vendorId, certificate_type_id: certTypeId, expiry_date: expiryDate || null },
              { onSuccess: () => setExpiryDate('') },
            )
          }}
        >
          <select
            required
            value={certTypeId}
            onChange={(e) => setCertTypeId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">-- Certificate type --</option>
            {(certTypes ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={addCertificate.isPending}
            className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Add certificate
          </button>
          {addCertificate.isError && <span className="text-sm text-red-600">{addCertificate.error.message}</span>}
        </form>
      )}
    </div>
  )
}

function PrequalificationSection({ vendorId, canWrite }: { vendorId: string; canWrite: boolean }) {
  const today = new Date().toISOString().slice(0, 10)
  const { data: prequal, isError, error } = useVendorPrequalification(vendorId, today)
  const decide = useDecidePrequalification(vendorId)
  const [status, setStatus] = useState('approved')

  return (
    <div className="mt-6">
      <h2 className="text-sm font-semibold text-slate-800">Prequalification (as of {today})</h2>
      {prequal && (
        <p className="mt-1 text-sm text-slate-700">
          Status: <span className="font-medium">{prequal.status}</span>
          {prequal.grade && ` · Grade ${prequal.grade}`}
        </p>
      )}
      {isError && (
        <p className="mt-1 text-sm text-slate-500">
          No decision on file as of today{error instanceof Error ? ` (${error.message})` : ''}.
        </p>
      )}
      {canWrite && (
        <form
          className="mt-2 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            decide.mutate({ status, effective_from: today })
          }}
        >
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="approved">Approved</option>
            <option value="suspended">Suspended</option>
            <option value="rejected">Rejected</option>
          </select>
          <button
            type="submit"
            disabled={decide.isPending}
            className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Record decision (effective today)
          </button>
          {decide.isError && <span className="text-sm text-red-600">{decide.error.message}</span>}
        </form>
      )}
    </div>
  )
}

export function VendorDetailPage() {
  const { vendorId } = useParams()
  const { hasRole } = useAuth()
  const canWriteVendor = hasRole(...WRITE_ROLES)
  const canWritePrequal = hasRole(...PREQUAL_WRITE_ROLES)
  const { data: vendor, isLoading, isError, error } = useVendor(vendorId)
  const { data: regions } = useVendorServiceRegions(vendorId)
  const scanDuplicates = useScanDuplicates(vendorId)

  if (isLoading) return <p className="p-6 text-slate-500">Loading...</p>
  if (isError) {
    return (
      <div className="p-6">
        <Link to="/vendors" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
          ← Vendors
        </Link>
        <p className="mt-4 text-red-600">{error.message}</p>
      </div>
    )
  }
  if (!vendor) return null

  return (
    <div className="p-6">
      <Link to="/vendors" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
        ← Vendors
      </Link>
      <div className="mt-2 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">{vendor.legal_name}</h1>
        {canWriteVendor && (
          <button
            type="button"
            disabled={scanDuplicates.isPending}
            onClick={() => scanDuplicates.mutate()}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Scan for duplicates
          </button>
        )}
      </div>
      {scanDuplicates.isSuccess && (
        <p className="mt-1 text-sm text-slate-600">
          {scanDuplicates.data.length === 0
            ? 'No new duplicate candidates found.'
            : `${scanDuplicates.data.length} candidate(s) found — see Vendor duplicate review.`}
        </p>
      )}
      {scanDuplicates.isError && <p className="mt-1 text-sm text-red-600">{scanDuplicates.error.message}</p>}

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <dt className="text-slate-500">Trade license</dt>
        <dd>{vendor.trade_license_no ?? '--'}</dd>
        <dt className="text-slate-500">License authority</dt>
        <dd>{vendor.license_authority ?? '--'}</dd>
        <dt className="text-slate-500">TRN/VAT</dt>
        <dd>{vendor.trn_vat_no ?? '--'}</dd>
        <dt className="text-slate-500">Emirate</dt>
        <dd>{vendor.emirate ?? '--'}</dd>
        <dt className="text-slate-500">Email</dt>
        <dd>{vendor.primary_email ?? '--'}</dd>
        <dt className="text-slate-500">Phone</dt>
        <dd>{vendor.primary_phone ?? '--'}</dd>
        <dt className="text-slate-500">Status</dt>
        <dd>{vendor.status}</dd>
        <dt className="text-slate-500">Service regions</dt>
        <dd>{regions && regions.length > 0 ? regions.join(', ') : '--'}</dd>
      </dl>
      <p className="mt-1 text-xs text-slate-500">
        Service regions are edited from Admin → Vendor service regions.
      </p>

      {vendorId && <CertificatesSection vendorId={vendorId} canWrite={canWritePrequal} />}
      {vendorId && <PrequalificationSection vendorId={vendorId} canWrite={canWritePrequal} />}
    </div>
  )
}
