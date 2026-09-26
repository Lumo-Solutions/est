import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useExportOriginalSettlement, useExportSettlement, usePreviewOriginalExport } from '../features/settlement/api'
import { useCurrentSettlement } from '../features/settlement/useCurrentSettlement'

export function ExportPage() {
  const { projectId } = useParams()
  const { current, isLoading } = useCurrentSettlement(projectId)
  const [includeVat, setIncludeVat] = useState(false)
  const exportGenerated = useExportSettlement(current?.id)
  const previewOriginal = usePreviewOriginalExport(current?.id)
  const exportOriginal = useExportOriginalSettlement(current?.id)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Export</h1>
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {!isLoading && !current && <p className="mt-4 text-sm text-slate-500">No settlement yet for this project.</p>}

      {current && (
        <div className="mt-4 space-y-6">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">Generated export</h2>
            <label className="mt-1 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={includeVat} onChange={(e) => setIncludeVat(e.target.checked)} />
              Include VAT (5%)
            </label>
            <button
              type="button"
              onClick={() => exportGenerated.mutate({ include_vat: includeVat, vat_pct: 5.0 })}
              disabled={exportGenerated.isPending}
              className="mt-2 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Download generated .xlsx
            </button>
            {exportGenerated.isError && <p className="mt-1 text-sm text-red-600">{exportGenerated.error.message}</p>}
          </div>

          <div>
            <h2 className="text-sm font-semibold text-slate-800">Export into the original workbook</h2>
            <button
              type="button"
              onClick={() => previewOriginal.mutate()}
              disabled={previewOriginal.isPending}
              className="mt-1 rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Preview fidelity report
            </button>
            {previewOriginal.isError && <p className="mt-1 text-sm text-red-600">{previewOriginal.error.message}</p>}

            {previewOriginal.data && (
              <div className="mt-2 rounded border border-slate-200 p-3 text-sm">
                <p className={previewOriginal.data.ok ? 'text-green-700' : 'text-amber-700'}>
                  {previewOriginal.data.ok ? 'No fidelity loss detected.' : 'Fidelity loss detected -- review below.'}
                </p>
                {previewOriginal.data.lost_features.length > 0 && (
                  <>
                    <p className="mt-1 text-xs font-semibold text-slate-600">Lost features</p>
                    <ul className="text-xs text-slate-600">
                      {previewOriginal.data.lost_features.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  </>
                )}
                {previewOriginal.data.unexpected_cell_changes.length > 0 && (
                  <>
                    <p className="mt-1 text-xs font-semibold text-slate-600">Unexpected cell changes</p>
                    <ul className="text-xs text-slate-600">
                      {previewOriginal.data.unexpected_cell_changes.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  </>
                )}
                <button
                  type="button"
                  onClick={() => exportOriginal.mutate()}
                  disabled={exportOriginal.isPending}
                  className="mt-2 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  Accept and download original .xlsx
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
