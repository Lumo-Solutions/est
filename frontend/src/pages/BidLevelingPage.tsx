import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { useProcurementPackages } from '../features/procurement/api'
import { useAcknowledgeExclusionFlag, useBidLevelingMatrix, useQuotationExclusionFlags, useQuotationTotals } from '../features/quotations/api'
import { formatMoney } from '../lib/format'
import { Role } from '../lib/roles'

// Mirrors backend/app/api/v1/routes/quotation_ingestion.py's _REVIEW_ROLES --
// same roles as every other quotation-review action (accept/reject line,
// reject quotation, promote, fx-rate).
const ACKNOWLEDGE_ROLES = [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// ExclusionFlagStatus (open/acknowledged/dismissed).
const FLAG_STATUS_TONE: Record<string, BadgeTone> = {
  open: 'warning',
  acknowledged: 'success',
  dismissed: 'neutral',
}

function ExclusionFlagsPanel({ quotationId }: { quotationId: string }) {
  const { hasRole } = useAuth()
  const { data: flags } = useQuotationExclusionFlags(quotationId)
  const acknowledge = useAcknowledgeExclusionFlag(quotationId)
  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-800">Exclusion flags and citations</h3>
      {flags && flags.length === 0 && <p className="mt-1 text-sm text-slate-500">None flagged.</p>}
      <ul className="mt-1 space-y-2">
        {(flags ?? []).map((f) => (
          <li key={f.id} className="rounded border border-warning-subtle bg-warning-subtle p-2 text-sm">
            <p className="font-medium text-amber-900">{f.flag_text}</p>
            <p className="mt-1 text-xs text-slate-600">
              "{f.source_quote_text}" {f.source_location && `(${f.source_location})`}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              {f.citation_verified ? (
                <span className="text-success">Citation verified</span>
              ) : (
                <span className="text-warning">Citation not verified -- review the source</span>
              )}
              <Badge tone={FLAG_STATUS_TONE[f.status] ?? 'neutral'}>{f.status}</Badge>
              {f.status !== 'acknowledged' && hasRole(...ACKNOWLEDGE_ROLES) && (
                <button
                  type="button"
                  disabled={acknowledge.isPending}
                  onClick={() => acknowledge.mutate(f.id)}
                  className="rounded text-slate-500 underline hover:text-slate-800 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                >
                  Acknowledge
                </button>
              )}
            </p>
          </li>
        ))}
      </ul>
      {acknowledge.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {acknowledge.error.message}
        </p>
      )}
    </div>
  )
}

export function BidLevelingPage() {
  const { projectId } = useParams()
  const { data: packages } = useProcurementPackages(projectId)
  const [packageId, setPackageId] = useState<string | null>(null)
  const { data: rows } = useBidLevelingMatrix(packageId ?? undefined)
  const { data: totals } = useQuotationTotals(packageId ?? undefined)
  const [selectedQuotationId, setSelectedQuotationId] = useState<string | null>(null)

  const totalsByQuotation = new Map((totals ?? []).map((t) => [t.quotation_id, t]))

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Bid-leveling matrix</h1>
      <select
        value={packageId ?? ''}
        onChange={(e) => setPackageId(e.target.value || null)}
        className="mt-4 rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      >
        <option value="">-- Package --</option>
        {(packages ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>

      {packageId && rows && rows.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">No bid-leveling rows for this package yet.</p>
      )}

      {rows && rows.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2 font-medium">BOQ item</th>
              <th className="font-medium">Vendor cells</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.boq_line_item_id} className="border-b border-slate-100 align-top hover:bg-slate-50">
                <td className="py-2">{row.boq_line_item_id.slice(0, 8)}</td>
                <td className="flex flex-wrap gap-2 py-2">
                  {row.cells.map((cell) => {
                    const total = totalsByQuotation.get(cell.quotation_id)
                    return (
                      <button
                        key={cell.quotation_id}
                        type="button"
                        onClick={() => setSelectedQuotationId(cell.quotation_id)}
                        className={`rounded border px-2 py-1 text-left text-xs tabular-nums transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
                          cell.quotation_id === selectedQuotationId
                            ? 'border-brand bg-brand-subtle'
                            : 'border-slate-200 hover:bg-slate-50'
                        }`}
                      >
                        <div>
                          {formatMoney(cell.unit_price, cell.currency)}
                          {cell.normalized_unit_price != null && (
                            <div className="text-slate-500">norm: {formatMoney(cell.normalized_unit_price, cell.currency)}</div>
                          )}
                        </div>
                        {(cell.arithmetic_mismatch || cell.quantity_mismatch || cell.uom_mismatch) && (
                          <div className="text-danger">mismatch</div>
                        )}
                        {total?.total_mismatch && <div className="text-danger">total mismatch</div>}
                      </button>
                    )
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selectedQuotationId && <ExclusionFlagsPanel quotationId={selectedQuotationId} />}
    </div>
  )
}
