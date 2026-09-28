import { useId, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { TextPromptModal } from '../components/TextPromptModal'
import { formatMoney } from '../lib/format'
import { useProcurementPackages, useRfqs } from '../features/procurement/api'
import {
  attachmentDownloadHref,
  useAcceptLineItem,
  usePromoteQuotationVersion,
  useQuotationAttachments,
  useQuotationLineItems,
  useQuotationsForRfq,
  useRejectLineItem,
  useRejectQuotation,
  useResolveCurrencyVat,
  useSetQuotationFxRate,
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

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// QuotationStatus (proposed/needs_review/extraction_empty/rejected) and
// QuotationLineItemStatus (proposed/needs_review/accepted/rejected).
const QUOTATION_STATUS_TONE: Record<string, BadgeTone> = {
  proposed: 'info',
  needs_review: 'warning',
  extraction_empty: 'neutral',
  rejected: 'danger',
}

const LINE_ITEM_STATUS_TONE: Record<string, BadgeTone> = {
  proposed: 'info',
  needs_review: 'warning',
  accepted: 'success',
  rejected: 'danger',
}

// backend/app/core/enums.py's AttachmentSafetyStatus -- pending/accepted/
// rejected_type/rejected_size/rejected_page_limit/rejected_macro/
// rejected_encrypted/rejected_archive.
function safetyStatusTone(status: string): BadgeTone {
  if (status === 'accepted') return 'success'
  if (status === 'pending') return 'warning'
  return 'danger'
}

function AttachmentsList({ quotationId }: { quotationId: string }) {
  const { data: attachments, isLoading, isError, error } = useQuotationAttachments(quotationId)

  if (isLoading) return <p className="mt-2 text-xs text-slate-500">Loading attachments...</p>
  if (isError)
    return (
      <p role="alert" className="mt-2 text-xs text-danger">
        {error.message}
      </p>
    )
  if (!attachments || attachments.length === 0) return <p className="mt-2 text-xs text-slate-500">No attachments.</p>

  return (
    <ul className="mt-2 space-y-1 text-xs">
      {attachments.map((a) => (
        <li key={a.id} className="flex items-center justify-between gap-2">
          <span>
            {a.filename} {a.is_primary && <span className="text-slate-600">(primary)</span>} --{' '}
            {(a.size_bytes / 1024).toFixed(1)} KB
          </span>
          {a.safety_status === 'accepted' ? (
            <a
              href={attachmentDownloadHref(a.id)}
              target="_blank"
              rel="noreferrer"
              className="rounded text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Download
            </a>
          ) : (
            <span title={a.rejection_reason ?? ''}>
              <Badge tone={safetyStatusTone(a.safety_status)}>{a.safety_status}</Badge>
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

function QuotationCard({ rfqId, quotation }: { rfqId: string; quotation: QuotationOut }) {
  const { hasRole } = useAuth()
  const canReview = hasRole(...REVIEW_ROLES)
  const { data: lineItems } = useQuotationLineItems(quotation.id)
  const acceptItem = useAcceptLineItem(quotation.id)
  const rejectItem = useRejectLineItem(quotation.id)
  const promote = usePromoteQuotationVersion(rfqId)
  const resolveCurrencyVat = useResolveCurrencyVat(rfqId)
  const rejectQuotation = useRejectQuotation(rfqId)
  const setFxRate = useSetQuotationFxRate()
  const [currency, setCurrency] = useState(quotation.currency ?? '')
  const [fxRate, setFxRateInput] = useState('')
  const [attachmentsOpen, setAttachmentsOpen] = useState(false)
  const [rejectPromptOpen, setRejectPromptOpen] = useState(false)
  const currencyInputId = useId()
  const fxRateInputId = useId()

  return (
    <div className={`rounded border p-3 ${quotation.is_current ? 'border-slate-400' : 'border-slate-200'}`}>
      <div className="flex items-center justify-between">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <span>
            v{quotation.version_no} {quotation.is_current && '(current)'}
          </span>
          <Badge tone={QUOTATION_STATUS_TONE[quotation.status] ?? 'neutral'}>{quotation.status}</Badge>
        </h4>
        {!quotation.is_current && canReview && (
          <button
            type="button"
            onClick={() => promote.mutate(quotation.id)}
            className="rounded text-xs text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Promote to current
          </button>
        )}
      </div>
      {promote.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {promote.error.message}
        </p>
      )}
      <p className="mt-1 text-xs tabular-nums text-slate-500">
        {quotation.stated_total != null ? formatMoney(quotation.stated_total, quotation.currency ?? 'AED') : '--'}
        {quotation.total_mismatch && <span className="text-danger"> (total mismatch)</span>}
      </p>

      {canReview && (
        <div className="mt-2 flex items-end gap-2">
          <div>
            <label htmlFor={currencyInputId} className="sr-only">
              Currency
            </label>
            <input
              id={currencyInputId}
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              placeholder="Currency"
              className="w-16 rounded border border-slate-300 px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          <button
            type="button"
            onClick={() => resolveCurrencyVat.mutate({ quotationId: quotation.id, currency, vatInclusive: true })}
            className="rounded text-xs text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Set currency (VAT-incl.)
          </button>
          <button
            type="button"
            onClick={() => setRejectPromptOpen(true)}
            className="rounded text-xs text-danger underline hover:text-red-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Reject quotation
          </button>
        </div>
      )}
      {resolveCurrencyVat.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {resolveCurrencyVat.error.message}
        </p>
      )}
      {rejectQuotation.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {rejectQuotation.error.message}
        </p>
      )}
      <TextPromptModal
        open={rejectPromptOpen}
        title="Reject quotation"
        message="Reject reason?"
        submitLabel="Reject"
        onCancel={() => setRejectPromptOpen(false)}
        onSubmit={(reason) => {
          rejectQuotation.mutate({ quotationId: quotation.id, reason })
          setRejectPromptOpen(false)
        }}
      />

      {canReview && (
        <div className="mt-2 flex items-end gap-2">
          <div>
            <label htmlFor={fxRateInputId} className="sr-only">
              FX rate to base
            </label>
            <input
              id={fxRateInputId}
              placeholder={quotation.fx_rate_to_base != null ? `Current: ${quotation.fx_rate_to_base}` : 'FX rate to base'}
              value={fxRate}
              onChange={(e) => setFxRateInput(e.target.value)}
              className="w-32 rounded border border-slate-300 px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          <button
            type="button"
            disabled={!fxRate || setFxRate.isPending}
            onClick={() =>
              setFxRate.mutate(
                { quotationId: quotation.id, data: { fx_rate_to_base: Number(fxRate), fx_rate_date: new Date().toISOString().slice(0, 10) } },
                { onSuccess: () => setFxRateInput('') },
              )
            }
            className="rounded text-xs text-slate-500 underline hover:text-slate-800 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Set FX rate
          </button>
        </div>
      )}
      {setFxRate.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {setFxRate.error.message}
        </p>
      )}

      <button
        type="button"
        onClick={() => setAttachmentsOpen((v) => !v)}
        className="mt-2 rounded text-xs text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        {attachmentsOpen ? 'Hide attachments' : 'Show attachments'}
      </button>
      {attachmentsOpen && <AttachmentsList quotationId={quotation.id} />}

      <table className="mt-2 w-full text-left text-xs">
        <thead className="border-b border-slate-200 text-slate-500">
          <tr>
            <th className="py-1 font-medium">Item</th>
            <th className="font-medium">Unit price</th>
            <th className="font-medium">Qty</th>
            <th className="font-medium">Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(lineItems ?? []).map((li) => (
            <tr key={li.id} className="border-t border-slate-100 hover:bg-slate-50">
              <td className="py-1">{li.vendor_description_text ?? li.vendor_item_text ?? '--'}</td>
              <td className="tabular-nums">
                {li.unit_price != null ? formatMoney(li.unit_price, quotation.currency ?? 'AED') : '--'}{' '}
                {li.arithmetic_mismatch && (
                  <span className="text-danger" title="Arithmetic mismatch">
                    !
                  </span>
                )}
              </td>
              <td className="tabular-nums">
                {li.quantity ?? '--'}{' '}
                {li.quantity_mismatch && (
                  <span className="text-danger" title="Quantity mismatch">
                    !
                  </span>
                )}
              </td>
              <td>
                <Badge tone={LINE_ITEM_STATUS_TONE[li.status] ?? 'neutral'}>{li.status}</Badge>
              </td>
              <td className="space-x-2">
                {canReview && (
                  <>
                    <button
                      type="button"
                      onClick={() => acceptItem.mutate(li.id)}
                      className="rounded text-emerald-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      onClick={() => rejectItem.mutate(li.id)}
                      className="rounded text-danger hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Reject
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {acceptItem.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {acceptItem.error.message}
        </p>
      )}
      {rejectItem.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {rejectItem.error.message}
        </p>
      )}
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
          aria-label="Package"
          value={packageId ?? ''}
          onChange={(e) => {
            setPackageId(e.target.value || null)
            setRfqId(null)
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        >
          <option value="">-- Package --</option>
          {(packages ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label="RFQ"
          value={rfqId ?? ''}
          onChange={(e) => setRfqId(e.target.value || null)}
          disabled={!packageId}
          className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
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
