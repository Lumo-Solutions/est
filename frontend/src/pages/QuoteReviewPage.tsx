import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useProcurementPackages, useRfqs } from '../features/procurement/api'
import {
  useAcceptLineItem,
  usePromoteQuotationVersion,
  useQuotationLineItems,
  useQuotationsForRfq,
  useRejectLineItem,
  useRejectQuotation,
  useResolveCurrencyVat,
} from '../features/quotations/api'
import { Role } from '../lib/roles'
import type { QuotationOut } from '../types/api'

// Mirrors backend/app/api/v1/routes/quotation_ingestion.py's _REVIEW_ROLES --
// accept/reject/promote/resolve-currency-vat/reject-quotation are
// procurement_head/bd_director/managing_director only server-side (notably
// NOT estimator or lead_estimator, even though this page is nav-gated to
// "all"). Before this fix, every one of these buttons was fully enabled for
// any role and had zero error feedback, so an estimator/lead_estimator saw
// working-looking controls that just silently 403'd.
const REVIEW_ROLES = [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

function QuotationCard({ rfqId, quotation }: { rfqId: string; quotation: QuotationOut }) {
  const { hasRole } = useAuth()
  const canReview = hasRole(...REVIEW_ROLES)
  const { data: lineItems } = useQuotationLineItems(quotation.id)
  const acceptItem = useAcceptLineItem(quotation.id)
  const rejectItem = useRejectLineItem(quotation.id)
  const promote = usePromoteQuotationVersion(rfqId)
  const resolveCurrencyVat = useResolveCurrencyVat(rfqId)
  const rejectQuotation = useRejectQuotation(rfqId)
  const [currency, setCurrency] = useState(quotation.currency ?? '')

  return (
    <div className={`rounded border p-3 ${quotation.is_current ? 'border-slate-400' : 'border-slate-200'}`}>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-800">
          v{quotation.version_no} {quotation.is_current && '(current)'} -- {quotation.status}
        </h4>
        {!quotation.is_current && canReview && (
          <button type="button" onClick={() => promote.mutate(quotation.id)} className="text-xs text-slate-600 underline">
            Promote to current
          </button>
        )}
      </div>
      {promote.isError && <p className="mt-1 text-xs text-red-600">{promote.error.message}</p>}
      <p className="mt-1 text-xs text-slate-500">
        {quotation.currency ?? '?'} {quotation.stated_total ?? '--'}
        {quotation.total_mismatch && <span className="text-red-600"> (total mismatch)</span>}
      </p>

      {canReview && (
        <div className="mt-2 flex items-end gap-2">
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            placeholder="Currency"
            className="w-16 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button
            type="button"
            onClick={() => resolveCurrencyVat.mutate({ quotationId: quotation.id, currency, vatInclusive: true })}
            className="text-xs text-slate-600 underline"
          >
            Set currency (VAT-incl.)
          </button>
          <button
            type="button"
            onClick={() => {
              const reason = window.prompt('Reject reason?')
              if (reason) rejectQuotation.mutate({ quotationId: quotation.id, reason })
            }}
            className="text-xs text-red-600 underline"
          >
            Reject quotation
          </button>
        </div>
      )}
      {resolveCurrencyVat.isError && <p className="mt-1 text-xs text-red-600">{resolveCurrencyVat.error.message}</p>}
      {rejectQuotation.isError && <p className="mt-1 text-xs text-red-600">{rejectQuotation.error.message}</p>}

      <table className="mt-2 w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th>Item</th>
            <th>Unit price</th>
            <th>Qty</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(lineItems ?? []).map((li) => (
            <tr key={li.id} className="border-t border-slate-100">
              <td>{li.vendor_description_text ?? li.vendor_item_text ?? '--'}</td>
              <td>
                {li.unit_price ?? '--'} {li.arithmetic_mismatch && <span className="text-red-600">!</span>}
              </td>
              <td>
                {li.quantity ?? '--'} {li.quantity_mismatch && <span className="text-red-600">!</span>}
              </td>
              <td>{li.status}</td>
              <td className="space-x-1">
                {canReview && (
                  <>
                    <button type="button" onClick={() => acceptItem.mutate(li.id)} className="text-green-700 underline">
                      Accept
                    </button>
                    <button type="button" onClick={() => rejectItem.mutate(li.id)} className="text-red-700 underline">
                      Reject
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {acceptItem.isError && <p className="mt-1 text-xs text-red-600">{acceptItem.error.message}</p>}
      {rejectItem.isError && <p className="mt-1 text-xs text-red-600">{rejectItem.error.message}</p>}
    </div>
  )
}

export function QuoteReviewPage() {
  const { projectId } = useParams()
  const { data: packages } = useProcurementPackages(projectId)
  const [packageId, setPackageId] = useState<string | null>(null)
  const { data: rfqs } = useRfqs(packageId ?? undefined)
  const [rfqId, setRfqId] = useState<string | null>(null)
  const { data: quotations } = useQuotationsForRfq(rfqId ?? undefined)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Quote review and acceptance</h1>

      <div className="mt-4 flex gap-4">
        <select
          value={packageId ?? ''}
          onChange={(e) => {
            setPackageId(e.target.value || null)
            setRfqId(null)
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">-- Package --</option>
          {(packages ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          value={rfqId ?? ''}
          onChange={(e) => setRfqId(e.target.value || null)}
          disabled={!packageId}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">-- RFQ --</option>
          {(rfqs ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.rfq_ref ?? r.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>

      {rfqId && (
        <div className="mt-4 space-y-3">
          {(quotations ?? []).map((q) => (
            <QuotationCard key={q.id} rfqId={rfqId} quotation={q} />
          ))}
          {quotations && quotations.length === 0 && <p className="text-sm text-slate-500">No quotations yet.</p>}
        </div>
      )}
    </div>
  )
}
