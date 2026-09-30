import { useMemo, useRef, useState } from 'react'
import { Badge } from '../../../components/Badge'
import { Button } from '../../../components/Button'
import type { BoqPdfExtractionDetail, BoqPdfRow, BoqPdfRowIn } from '../../../types/api'
import { openBoqPdfSource } from './api'

interface DraftRow {
  key: string
  row_id?: string
  page: number
  item_no: string
  description: string
  uom: string
  quantity: string
  aiRead: boolean
  confidence: number | null
  edited: boolean
  errors: string[]
}

function fromServer(row: BoqPdfRow): DraftRow {
  return {
    key: row.row_id,
    row_id: row.row_id,
    page: row.page,
    item_no: row.item_no ?? '',
    description: row.description ?? '',
    uom: row.uom ?? '',
    quantity: row.quantity == null ? '' : String(row.quantity),
    aiRead: row.ai_read,
    confidence: row.confidence,
    edited: row.edited,
    errors: row.errors,
  }
}

function parseQuantity(value: string): number | null | undefined {
  const t = value.trim()
  if (t === '') return null
  const n = Number(t.replace(/,/g, ''))
  return Number.isFinite(n) ? n : undefined // undefined = not a number
}

function toPayload(rows: DraftRow[]): BoqPdfRowIn[] {
  return rows.map((r) => ({
    ...(r.row_id ? { row_id: r.row_id } : {}),
    item_no: r.item_no.trim(),
    description: r.description.trim(),
    uom: r.uom.trim(),
    quantity: parseQuantity(r.quantity) ?? null,
    page: r.page,
  }))
}

const inputClass =
  'w-full rounded border border-slate-300 px-2 py-1 text-sm text-ink focus:border-brand focus:ring-1 focus:ring-brand focus:outline-none'
const toggleClass = 'flex items-center gap-2 text-sm text-ink'

export function PdfRowsGrid({
  extraction,
  onSave,
  onImport,
  saving = false,
  importing = false,
  saveError,
  importError,
}: {
  extraction: BoqPdfExtractionDetail
  onSave: (rows: BoqPdfRowIn[]) => Promise<BoqPdfExtractionDetail>
  onImport: () => void
  saving?: boolean
  importing?: boolean
  saveError?: string | null
  importError?: string | null
}) {
  const [draft, setDraft] = useState<DraftRow[]>(() => extraction.rows.map(fromServer))
  const [dirty, setDirty] = useState(false)
  const [onlyErrors, setOnlyErrors] = useState(false)
  const [onlyAi, setOnlyAi] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const newKey = useRef(0)

  // Pick up server-side changes (e.g. a retry) only while there is nothing unsaved.
  const [syncedRows, setSyncedRows] = useState(extraction.rows)
  if (syncedRows !== extraction.rows) {
    setSyncedRows(extraction.rows)
    if (!dirty) setDraft(extraction.rows.map(fromServer))
  }

  const update = (key: string, patch: Partial<DraftRow>) => {
    setDraft((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
    setDirty(true)
  }
  const remove = (key: string) => {
    setDraft((rows) => rows.filter((r) => r.key !== key))
    setDirty(true)
  }
  const add = () => {
    newKey.current += 1
    setDraft((rows) => [
      ...rows,
      {
        key: `new-${newKey.current}`,
        page: rows.length ? rows[rows.length - 1].page : 1,
        item_no: '',
        description: '',
        uom: '',
        quantity: '',
        aiRead: false,
        confidence: null,
        edited: true,
        errors: [],
      },
    ])
    setDirty(true)
  }

  const localInvalid = draft.some((r) => parseQuantity(r.quantity) === undefined)
  const errorRows = dirty ? draft.filter((r) => r.errors.length > 0).length : extraction.error_count
  const aiRows = draft.filter((r) => r.aiRead).length
  const visible = useMemo(
    () => draft.filter((r) => (!onlyErrors || r.errors.length > 0) && (!onlyAi || r.aiRead)),
    [draft, onlyErrors, onlyAi],
  )

  const save = async () => {
    const saved = await onSave(toPayload(draft))
    setDraft(saved.rows.map(fromServer))
    setDirty(false)
  }

  const canImport = !dirty && extraction.error_count === 0 && draft.length > 0 && !importing && !saving
  const importTitle = dirty
    ? 'Save your changes first'
    : extraction.error_count > 0
      ? 'Fix the rows with errors first'
      : undefined

  return (
    <div className="mt-4">
      <p className="text-sm text-ink-2" data-testid="pdf-summary">
        {draft.length} {draft.length === 1 ? 'row' : 'rows'}, {errorRows} with errors, {aiRows} AI-read
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-4">
        <label className={toggleClass}>
          <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} />
          Only rows with errors
        </label>
        <label className={toggleClass}>
          <input type="checkbox" checked={onlyAi} onChange={(e) => setOnlyAi(e.target.checked)} />
          Only AI-read
        </label>
      </div>

      <div className="relative mt-2 overflow-x-auto rounded-card bg-white p-2">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-muted">
            <tr>
              <th className="py-2 pr-2 font-medium">Page</th>
              <th className="pr-2 font-medium">Item No</th>
              <th className="pr-2 font-medium">Description</th>
              <th className="pr-2 font-medium">Unit</th>
              <th className="pr-2 font-medium">Quantity</th>
              <th className="pr-2 font-medium">Status</th>
              <th className="font-medium">
                <span className="sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const badQty = parseQuantity(row.quantity) === undefined
              const n = draft.indexOf(row) + 1
              return (
                <tr
                  key={row.key}
                  data-testid="pdf-row"
                  className={`border-b border-row-rule align-top ${row.errors.length > 0 || badQty ? 'bg-danger-subtle' : ''}`}
                >
                  <td className="py-2 pr-2 whitespace-nowrap">
                    {row.row_id ? (
                      <button
                        type="button"
                        onClick={() => {
                          setOpenError(null)
                          openBoqPdfSource(extraction.id, row.page).catch((e: unknown) =>
                            setOpenError(e instanceof Error ? e.message : 'Could not open the PDF'),
                          )
                        }}
                        aria-label={`Open source PDF at page ${row.page} for row ${n}`}
                        className="rounded tabular-nums text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                      >
                        p. {row.page}
                      </button>
                    ) : (
                      <span className="tabular-nums text-ink-2">p. {row.page}</span>
                    )}
                  </td>
                  <td className="w-28 pr-2">
                    <input
                      aria-label={`Item no, row ${n}`}
                      value={row.item_no}
                      onChange={(e) => update(row.key, { item_no: e.target.value })}
                      className={inputClass}
                    />
                  </td>
                  <td className="min-w-64 pr-2">
                    <input
                      aria-label={`Description, row ${n}`}
                      value={row.description}
                      onChange={(e) => update(row.key, { description: e.target.value })}
                      className={inputClass}
                    />
                    {row.errors.length > 0 && (
                      <p className="mt-1 text-xs text-danger">
                        {row.errors.join('; ')}
                        {dirty ? ' (re-checked when you save)' : ''}
                      </p>
                    )}
                    {badQty && <p className="mt-1 text-xs text-danger">Quantity must be a number</p>}
                  </td>
                  <td className="w-24 pr-2">
                    <input
                      aria-label={`Unit, row ${n}`}
                      value={row.uom}
                      onChange={(e) => update(row.key, { uom: e.target.value })}
                      className={inputClass}
                    />
                  </td>
                  <td className="w-28 pr-2">
                    <input
                      aria-label={`Quantity, row ${n}`}
                      inputMode="decimal"
                      value={row.quantity}
                      onChange={(e) => update(row.key, { quantity: e.target.value })}
                      className={`${inputClass} tabular-nums`}
                    />
                  </td>
                  <td className="pr-2 whitespace-nowrap">
                    <span className="flex flex-wrap gap-1">
                      {row.aiRead && (
                        <Badge tone="warning">
                          AI-read{row.confidence != null ? ` ${Math.round(row.confidence * 100)}%` : ''}
                        </Badge>
                      )}
                      {row.edited && <Badge tone="info">Edited</Badge>}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() => remove(row.key)}
                      aria-label={`Remove row ${n}`}
                      className="rounded px-2 py-1 text-sm text-red-700 hover:bg-danger-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              )
            })}
            {visible.length === 0 && (
              <tr>
                <td colSpan={7} className="py-4 text-center text-ink-2">
                  {draft.length === 0 ? 'No rows were read from this PDF. Add rows by hand.' : 'No rows match the filters.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {openError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {openError}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={add}>
          Add row
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={!dirty || localInvalid}
          loading={saving}
          onClick={() => {
            save().catch(() => undefined) // surfaced through saveError
          }}
        >
          Save changes
        </Button>
        {dirty && (
          <span role="status" className="text-sm font-medium text-amber-800">
            Unsaved changes. Save before importing.
          </span>
        )}
      </div>
      {saveError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {saveError}
        </p>
      )}

      <p className="mt-3 max-w-2xl text-sm text-ink-2">
        The original-workbook export is not available for PDF sources. The generated export still works after import.
      </p>

      <div className="mt-3">
        <Button loading={importing} disabled={!canImport} title={importTitle} onClick={onImport}>
          Import {draft.length} {draft.length === 1 ? 'item' : 'items'}
        </Button>
        {importError && (
          <p role="alert" className="mt-1 text-xs text-danger">
            {importError}
          </p>
        )}
      </div>
    </div>
  )
}
