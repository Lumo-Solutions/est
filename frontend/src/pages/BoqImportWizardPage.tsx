import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useBoqImportCommit, useBoqImportPreview } from '../features/boq/api'
import type { BoqImportColumnMappingIn } from '../types/api'
import { PageTitle } from '../components/PageTitle'

const EMPTY_MAPPING: BoqImportColumnMappingIn = {
  item_no_column: '',
  description_column: '',
  uom_column: '',
  quantity_column: '',
  parent_column: '',
  rate_column: '',
  amount_column: '',
  header_row: 1,
}

function cleanMapping(mapping: BoqImportColumnMappingIn): BoqImportColumnMappingIn {
  const cleaned: BoqImportColumnMappingIn = { ...mapping }
  for (const key of ['uom_column', 'quantity_column', 'parent_column', 'rate_column', 'amount_column'] as const) {
    if (!cleaned[key]) cleaned[key] = null
  }
  return cleaned
}

export function BoqImportWizardPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [mapping, setMapping] = useState<BoqImportColumnMappingIn>(EMPTY_MAPPING)
  const [previewedKey, setPreviewedKey] = useState<string | null>(null)
  const preview = useBoqImportPreview(projectId)
  const commit = useBoqImportCommit(projectId)

  const currentKey = file ? `${file.name}:${JSON.stringify(mapping)}` : null
  const canCommit = preview.data != null && previewedKey === currentKey && preview.data.error_count === 0

  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>BOQ import wizard</PageTitle>

      <div className="mt-4">
        <label className="mb-1 block text-sm text-ink" htmlFor="boq-file">
          BOQ file (Excel/CSV)
        </label>
        <input
          id="boq-file"
          type="file"
          accept=".xlsx,.xls,.csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
      </div>

      <div className="mt-4 grid max-w-lg grid-cols-2 gap-2">
        {(
          [
            ['item_no_column', 'Item No column *'],
            ['description_column', 'Description column *'],
            ['uom_column', 'UoM column'],
            ['quantity_column', 'Quantity column'],
            ['parent_column', 'Parent item no column'],
            ['rate_column', 'Rate column'],
            ['amount_column', 'Amount column'],
            ['header_row', 'Header row'],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label className="mb-1 block text-sm text-ink" htmlFor={key}>
              {label}
            </label>
            <input
              id={key}
              value={mapping[key] ?? ''}
              onChange={(e) =>
                setMapping((prev) => ({
                  ...prev,
                  [key]: key === 'header_row' ? Number(e.target.value) : e.target.value,
                }))
              }
              className="w-full rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
            />
          </div>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          disabled={!file || !mapping.item_no_column || !mapping.description_column || preview.isPending}
          onClick={() => {
            if (!file) return
            preview.mutate({ file, mapping: cleanMapping(mapping) }, { onSuccess: () => setPreviewedKey(currentKey) })
          }}
          className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Preview
        </button>
        <button
          type="button"
          disabled={!canCommit || commit.isPending}
          onClick={() => {
            if (!file) return
            commit.mutate(
              { file, mapping: cleanMapping(mapping) },
              { onSuccess: () => navigate(`/projects/${projectId}/boq`) },
            )
          }}
          className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
        >
          Commit
        </button>
      </div>
      {preview.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {preview.error.message}
        </p>
      )}
      {commit.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {commit.error.message}
        </p>
      )}

      {preview.data && (
        <div className="mt-4">
          <p className="text-sm text-ink-2">
            {preview.data.valid_count} valid, {preview.data.error_count} with errors.
          </p>
          <div className="overflow-x-auto rounded-card bg-white p-2">
            <table className="mt-2 w-full text-left text-sm">
              <thead className="border-b border-hairline text-muted">
                <tr>
                  <th className="py-2 font-medium">Row</th>
                  <th className="font-medium">Item No</th>
                  <th className="font-medium">Description</th>
                  <th className="font-medium">Qty</th>
                  <th className="font-medium">Errors</th>
                </tr>
              </thead>
              <tbody>
                {preview.data.rows.map((row) => (
                  <tr
                    key={row.row_number}
                    className={`border-b border-row-rule ${row.errors.length > 0 ? 'bg-danger-subtle' : 'hover:bg-canvas'}`}
                  >
                    <td className="py-2 tabular-nums">{row.row_number}</td>
                    <td>{row.item_no ?? '--'}</td>
                    <td>{row.description ?? '--'}</td>
                    <td className="tabular-nums">{row.boq_quantity ?? '--'}</td>
                    <td className="text-danger">{row.errors.join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
