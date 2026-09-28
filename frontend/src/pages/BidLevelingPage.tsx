import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useProcurementPackages } from '../features/procurement/api'
import { useAcknowledgeExclusionFlag, useBidLevelingMatrix, useQuotationExclusionFlags, useQuotationTotals } from '../features/quotations/api'
import { Role } from '../lib/roles'

// Mirrors backend/app/api/v1/routes/quotation_ingestion.py's _REVIEW_ROLES --
// same roles as every other quotation-review action (accept/reject line,
// reject quotation, promote, fx-rate).
const ACKNOWLEDGE_ROLES = [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

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
          <li key={f.id} className="rounded border border-amber-200 bg-amber-50 p-2 text-sm">
            <p className="font-medium text-amber-900">{f.flag_text}</p>
            <p className="mt-1 text-xs text-slate-600">
              "{f.source_quote_text}" {f.source_location && `(${f.source_location})`}
            </p>
            <p className="mt-1 flex items-center gap-2 text-xs">
              {f.citation_verified ? (
                <span className="text-green-700">Citation verified</span>
              ) : (
                <span className="text-amber-700">Citation not verified -- review the source</span>
              )}
              {' · '}
              {f.status}
              {f.status !== 'acknowledged' && hasRole(...ACKNOWLEDGE_ROLES) && (
                <button
                  type="button"
                  disabled={acknowledge.isPending}
                  onClick={() => acknowledge.mutate(f.id)}
                  className="text-slate-600 underline disabled:opacity-50"
                >
                  Acknowledge
                </button>
              )}
            </p>
          </li>
        ))}
      </ul>
      {acknowledge.isError && <p className="mt-1 text-xs text-red-600">{acknowledge.error.message}</p>}
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
        className="mt-4 rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">-- Package --</option>
        {(packages ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>

      {rows && rows.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th>BOQ item</th>
              <th>Vendor cells</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.boq_line_item_id} className="border-b border-slate-100 align-top">
                <td className="py-2">{row.boq_line_item_id.slice(0, 8)}</td>
                <td className="flex flex-wrap gap-2 py-2">
                  {row.cells.map((cell) => {
                    const total = totalsByQuotation.get(cell.quotation_id)
                    return (
                      <button
                        key={cell.quotation_id}
                        type="button"
                        onClick={() => setSelectedQuotationId(cell.quotation_id)}
                        className={`rounded border px-2 py-1 text-left text-xs ${
                          cell.quotation_id === selectedQuotationId ? 'border-slate-500 bg-slate-100' : 'border-slate-200'
                        }`}
                      >
                        <div>
                          {cell.unit_price} {cell.currency}
                          {cell.normalized_unit_price && <div className="text-slate-500">norm: {cell.normalized_unit_price}</div>}
                        </div>
                        {(cell.arithmetic_mismatch || cell.quantity_mismatch || cell.uom_mismatch) && (
                          <div className="text-red-600">mismatch</div>
                        )}
                        {total?.total_mismatch && <div className="text-red-600">total mismatch</div>}
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
