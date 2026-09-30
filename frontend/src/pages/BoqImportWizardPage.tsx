import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { SelectField } from '../components/Field'
import { useAuth } from '../auth/AuthContext'
import { Role } from '../lib/roles'
import { fetchTenderDocumentFile, useBoqPrefill, useTenderDocument } from '../features/tenderIntake/api'
import { PdfImportFlow } from '../features/boq/pdf/PdfImportFlow'
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

// Mirrors the backend's PDF extraction roles (lead_estimator, procurement_head,
// managing_director); other roles get a 403 from the extraction endpoints.
const PDF_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

function cleanMapping(mapping: BoqImportColumnMappingIn): BoqImportColumnMappingIn {
  const cleaned: BoqImportColumnMappingIn = { ...mapping }
  for (const key of ['uom_column', 'quantity_column', 'parent_column', 'rate_column', 'amount_column'] as const) {
    if (!cleaned[key]) cleaned[key] = null
  }
  if (cleaned.sheet_name === '') cleaned.sheet_name = null
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

  // Deep link from the tender documents tab: ?document=<id> pre-fills the file
  // and mapping. The user still runs Preview and Commit themselves.
  const [searchParams] = useSearchParams()
  const documentId = searchParams.get('document')
  const { hasRole } = useAuth()
  const canPdf = hasRole(...PDF_ROLES)
  // A classified PDF BOQ has no sheets to map: detect it from the document
  // itself and skip the workbook prefill (which would only fail).
  const tenderDoc = useTenderDocument(documentId ?? undefined)
  const docIsPdf = tenderDoc.data?.ext?.toLowerCase().replace('.', '') === 'pdf'
  const prefillId = documentId && (tenderDoc.isSuccess || tenderDoc.isError) && !docIsPdf ? documentId : null
  const prefill = useBoqPrefill(prefillId)
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null)
  const [prefillError, setPrefillError] = useState<string | null>(null)
  const prefillData = prefill.data
  useEffect(() => {
    if (!documentId || !prefillId || !prefillData) return
    let cancelled = false
    fetchTenderDocumentFile(documentId, prefillData.filename)
      .then((f) => {
        if (cancelled) return
        const suggested = prefillData.suggested_mapping ?? {}
        const text = (k: string) => (suggested[k] == null ? '' : String(suggested[k]))
        const headerRow = Number(suggested.header_row ?? prefillData.header_row ?? 1)
        setFile(f)
        setMapping({
          item_no_column: text('item_no_column'),
          description_column: text('description_column'),
          uom_column: text('uom_column'),
          quantity_column: text('quantity_column'),
          parent_column: text('parent_column'),
          rate_column: text('rate_column'),
          amount_column: text('amount_column'),
          header_row: Number.isFinite(headerRow) && headerRow > 0 ? headerRow : 1,
          sheet_name: text('sheet_name') || prefillData.sheet_name || prefillData.sheet_names[0] || '',
        })
        setPrefillError(null)
        setPrefillNotice(
          `Pre-filled from tender document ${prefillData.filename}. Check the sheet and column mapping, then run the dry run.`,
        )
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setPrefillNotice(null)
        setPrefillError(e instanceof Error ? e.message : 'Could not load the tender document file')
      })
    return () => {
      cancelled = true
    }
  }, [documentId, prefillId, prefillData])

  const fileIsPdf = file ? file.name.toLowerCase().endsWith('.pdf') : false
  const isPdf = fileIsPdf || (!file && docIsPdf)

  const currentKey = file ? `${file.name}:${JSON.stringify(mapping)}` : null
  const canCommit = preview.data != null && previewedKey === currentKey && preview.data.error_count === 0

  return (
    <div className="mx-6 my-6 rounded-card bg-white p-6 xl:mx-10">
      <PageTitle>BOQ import wizard</PageTitle>

      <div className="mt-4">
        <label className="mb-1 block text-sm text-ink" htmlFor="boq-file">
          BOQ file ({canPdf ? 'Excel/CSV/PDF' : 'Excel/CSV'})
        </label>
        <input
          id="boq-file"
          type="file"
          accept={canPdf ? '.xlsx,.xls,.csv,.pdf' : '.xlsx,.xls,.csv'}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
      </div>

      {isPdf && projectId && (
        <PdfImportFlow
          key={file ? `${file.name}:${file.size}` : `doc:${documentId}`}
          projectId={projectId}
          file={file}
          documentId={file ? null : documentId}
          sourceName={file?.name ?? tenderDoc.data?.original_filename ?? 'the PDF'}
          canImport={canPdf}
        />
      )}

      {!isPdf && prefillNotice && (
        <p role="status" className="mt-4 text-sm text-ink-2">
          {prefillNotice}
        </p>
      )}
      {!isPdf && (prefillError || (prefillId && prefill.isError)) && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {prefillError ?? (prefill.error instanceof Error ? prefill.error.message : 'Could not load the tender document')}
          {' '}You can still choose a file and map the columns by hand.
        </p>
      )}
      {!isPdf && prefillData && prefillData.sheet_names.length > 1 && (
        <div className="mt-4 max-w-lg">
          <SelectField
            label="Sheet"
            value={mapping.sheet_name ?? ''}
            onChange={(e) => setMapping((prev) => ({ ...prev, sheet_name: e.target.value }))}
          >
            {prefillData.sheet_names.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </SelectField>
        </div>
      )}

      {!isPdf && (
      <>
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
          <div className="relative overflow-x-auto rounded-card bg-white p-2">
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
      </>
      )}
    </div>
  )
}
