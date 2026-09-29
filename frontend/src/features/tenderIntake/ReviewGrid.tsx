import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import type { CellValueChangedEvent, ColDef, GridApi, ICellRendererParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { confidenceTone, flagLabel, formatConfidence, statusTone } from './lib'
import type { TenderClass, TenderDocument } from './types'

ModuleRegistry.registerModules([AllCommunityModule])

// Same theme parameters as features/boq/BoqReconciliationGrid.tsx.
const installtecGridTheme = themeQuartz.withParams({
  accentColor: '#1814F3', // --color-brand
  foregroundColor: '#232323', // --color-ink
  headerBackgroundColor: '#F5F7FA', // --color-canvas
  headerTextColor: '#4F6FA5', // --color-muted (4.72:1 on canvas)
  oddRowBackgroundColor: '#FFFFFF',
  rowHoverColor: '#F5F7FA',
  borderColor: '#E6EFF5', // --color-hairline
  fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
  fontSize: 13,
})

export interface GridHandlers {
  onView: (doc: TenderDocument) => void
  onConfirm: (doc: TenderDocument) => void
  onExclude: (doc: TenderDocument) => void
  onRerun: (doc: TenderDocument) => void
  onReclassify: (doc: TenderDocument, code: string) => void
  onEdit: (doc: TenderDocument, field: 'title' | 'document_number' | 'revision_label', value: string, rollback: () => void) => void
}

const fileName = (d: TenderDocument) => d.archive_path ?? d.original_filename
const linkClass =
  'rounded text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

function RoutedInfo({ doc }: { doc: TenderDocument }) {
  const ref = doc.routed_ref ?? {}
  switch (doc.routed_kind) {
    case 'drawing':
      return (
        <span className="flex items-center gap-2">
          <Link to={`/projects/${doc.project_id}/drawings/${String(ref.drawing_id)}`} className={linkClass}>
            Open drawing
          </Link>
          {ref.not_measurable ? <span className="text-ink-2">Not measurable</span> : null}
        </span>
      )
    case 'boq_wizard':
      return (
        <Link
          to={`/projects/${doc.project_id}/boq/import?document=${doc.id}`}
          aria-label={`Open ${fileName(doc)} in BOQ import wizard`}
          className={linkClass}
        >
          Open in BOQ import wizard
        </Link>
      )
    case 'register':
      return <span className="text-ink-2">In document register</span>
    case 'addendum':
      return <span className="text-ink-2">In addenda register</span>
    case 'duplicate':
      return <span className="text-ink-2">Duplicate, not routed again</span>
    case 'convert_dwg':
      return <span className="text-ink-2">Stored; convert to DXF or PDF</span>
    default:
      return null
  }
}

export function ReviewGrid({
  rows,
  classes,
  canConfirm,
  handlers,
  onSelectionChange,
  onGridReady,
  className = 'h-[560px]',
}: {
  rows: TenderDocument[]
  classes: TenderClass[]
  canConfirm: boolean
  handlers: GridHandlers
  onSelectionChange: (ids: string[]) => void
  onGridReady?: (api: GridApi<TenderDocument>) => void
  className?: string
}) {
  const handlersRef = useRef(handlers)
  useEffect(() => {
    handlersRef.current = handlers
  })

  const classLabel = useMemo(() => {
    const m = new Map(classes.map((c) => [c.code, c.label]))
    return (code: string) => m.get(code) ?? code
  }, [classes])

  const columnDefs = useMemo<ColDef<TenderDocument>[]>(() => {
    const editable = (p: { data?: TenderDocument }) => canConfirm && p.data?.status === 'proposed'
    const editCol = (field: 'title' | 'document_number' | 'revision_label', headerName: string, width: number): ColDef<TenderDocument> => ({
      field,
      headerName,
      width,
      editable,
      valueFormatter: (p) => (p.value == null || p.value === '' ? '--' : String(p.value)),
    })
    return [
      {
        colId: 'file',
        headerName: 'File',
        width: 260,
        pinned: 'left',
        valueGetter: (p) => (p.data ? fileName(p.data) : ''),
        cellRenderer: (p: ICellRendererParams<TenderDocument>) =>
          p.data ? (
            <span className="flex flex-col leading-tight">
              <span className="truncate" title={fileName(p.data)}>
                {fileName(p.data)}
              </span>
              {p.data.duplicate_of_id && (
                <span className="truncate text-xs text-ink-2">Duplicate of {p.data.duplicate_of_id.slice(0, 8)}</span>
              )}
            </span>
          ) : null,
      },
      {
        colId: 'doc_class',
        headerName: 'Class',
        width: 220,
        valueGetter: (p) => (p.data?.doc_class ? classLabel(p.data.doc_class) : '--'),
        cellRenderer: (p: ICellRendererParams<TenderDocument>) => {
          const d = p.data
          if (!d) return null
          const label = d.doc_class ? classLabel(d.doc_class) : '--'
          const text = d.sub_type ? `${label} / ${d.sub_type}` : label
          if (!(canConfirm && d.status === 'proposed')) return <span>{text}</span>
          const options = classes.some((c) => c.code === d.doc_class) || !d.doc_class ? classes : [...classes, { code: d.doc_class, label: d.doc_class, default_label: d.doc_class, enabled: true, sort_order: 0 }]
          return (
            <select
              aria-label={`Class for ${fileName(d)}`}
              value={d.doc_class ?? ''}
              onChange={(e) => handlersRef.current.onReclassify(d, e.target.value)}
              className="w-full rounded border border-outline bg-white px-1 py-0.5 text-[13px] text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand"
            >
              {!d.doc_class && <option value="">--</option>}
              {options.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          )
        },
      },
      {
        colId: 'confidence',
        headerName: 'Confidence',
        width: 120,
        valueGetter: (p) => p.data?.confidence ?? null,
        cellRenderer: (p: ICellRendererParams<TenderDocument>) =>
          p.data?.confidence == null ? (
            <span>--</span>
          ) : (
            <Badge tone={confidenceTone(p.data.confidence)}>{formatConfidence(p.data.confidence)}</Badge>
          ),
      },
      editCol('document_number', 'Number', 140),
      editCol('title', 'Title', 220),
      editCol('revision_label', 'Revision', 100),
      {
        colId: 'evidence',
        headerName: 'Evidence',
        width: 100,
        sortable: false,
        cellRenderer: (p: ICellRendererParams<TenderDocument>) =>
          p.data ? (
            <Button size="sm" variant="secondary" aria-label={`View evidence for ${fileName(p.data)}`} onClick={() => handlersRef.current.onView(p.data!)}>
              View
            </Button>
          ) : null,
      },
      {
        colId: 'flags',
        headerName: 'Flags',
        width: 260,
        sortable: false,
        cellRenderer: (p: ICellRendererParams<TenderDocument>) => (
          <span className="flex flex-wrap items-center gap-1">
            {(p.data?.flags ?? []).map((f) => (
              <Badge key={f} tone="neutral">
                {flagLabel(f)}
              </Badge>
            ))}
          </span>
        ),
      },
      {
        colId: 'status',
        headerName: 'Status',
        width: 120,
        valueGetter: (p) => p.data?.status ?? '',
        cellRenderer: (p: ICellRendererParams<TenderDocument>) =>
          p.data ? <Badge tone={statusTone(p.data.status)}>{p.data.status}</Badge> : null,
      },
      {
        colId: 'actions',
        headerName: 'Actions',
        width: 340,
        sortable: false,
        cellRenderer: (p: ICellRendererParams<TenderDocument>) => {
          const d = p.data
          if (!d) return null
          const name = fileName(d)
          const h = handlersRef.current
          return (
            <span className="flex items-center gap-2">
              {canConfirm && d.status === 'proposed' && (
                <>
                  <Button size="sm" aria-label={`Confirm ${name}`} onClick={() => h.onConfirm(d)}>
                    Confirm
                  </Button>
                  <Button size="sm" variant="secondary" aria-label={`Exclude ${name}`} onClick={() => h.onExclude(d)}>
                    Exclude
                  </Button>
                  <Button size="sm" variant="secondary" aria-label={`Re-run ${name}`} onClick={() => h.onRerun(d)}>
                    Re-run
                  </Button>
                </>
              )}
              {canConfirm && d.status === 'failed' && (
                <>
                  <Button size="sm" variant="secondary" aria-label={`Re-run ${name}`} onClick={() => h.onRerun(d)}>
                    Re-run
                  </Button>
                  <Button size="sm" variant="secondary" aria-label={`Exclude ${name}`} onClick={() => h.onExclude(d)}>
                    Exclude
                  </Button>
                </>
              )}
              {d.status === 'routed' && <RoutedInfo doc={d} />}
              {d.status === 'rejected' && d.rejection_reason && (
                <span className="truncate text-ink-2" title={d.rejection_reason}>
                  {d.rejection_reason}
                </span>
              )}
              {d.status === 'failed' && d.error_message && (
                <span className="truncate text-danger" title={d.error_message}>
                  {d.error_message}
                </span>
              )}
            </span>
          )
        },
      },
    ]
  }, [canConfirm, classes, classLabel])

  const onCellValueChanged = (e: CellValueChangedEvent<TenderDocument>) => {
    if (e.source === 'rollback' || !e.data) return
    const field = e.colDef.field as 'title' | 'document_number' | 'revision_label'
    const doc = e.data
    const rollback = () => e.node.setDataValue(field, e.oldValue, 'rollback')
    handlersRef.current.onEdit(doc, field, String(e.newValue ?? ''), rollback)
  }

  return (
    <div className={`w-full ${className}`}>
      <AgGridReact<TenderDocument>
        theme={installtecGridTheme}
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={{ resizable: true, sortable: true, suppressMovable: true }}
        getRowId={(p) => p.data.id}
        rowHeight={44}
        // ~11 columns: virtualising them only hides Status/Flags/Actions from narrower windows
        // (and from assistive tech and tests) for no performance gain. Rows stay virtualised.
        suppressColumnVirtualisation
        singleClickEdit
        stopEditingWhenCellsLoseFocus
        rowSelection={
          canConfirm
            ? {
                mode: 'multiRow',
                checkboxes: true,
                headerCheckbox: true,
                enableClickSelection: false,
                selectAll: 'all',
                isRowSelectable: (node) => node.data?.status === 'proposed',
              }
            : undefined
        }
        onSelectionChanged={(e) => onSelectionChange(e.api.getSelectedRows().map((r) => r.id))}
        onCellValueChanged={onCellValueChanged}
        onGridReady={(e) => onGridReady?.(e.api)}
      />
    </div>
  )
}
