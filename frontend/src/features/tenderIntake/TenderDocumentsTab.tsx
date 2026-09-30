import type { GridApi } from 'ag-grid-community'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { controlClasses } from '../../components/Field'
import { Modal } from '../../components/Modal'
import { Pagination } from '../../components/Pagination'
import { SkeletonRows } from '../../components/Skeleton'
import { TextPromptModal } from '../../components/TextPromptModal'
import { AddendaRegister } from './AddendaRegister'
import { DocumentRegister } from './DocumentRegister'
import { EvidenceModal } from './EvidenceModal'
import { ReviewGrid, type GridHandlers } from './ReviewGrid'
import { UploadPanel } from './UploadPanel'
import {
  useBulkConfirm,
  useConfirmDocument,
  useEditMetadata,
  useExclude,
  useReclassify,
  useRerun,
  useTenderClasses,
  useTenderDocuments,
  useTenderPackages,
} from './api'
import { CONFIRM_ROLES, DOC_STATUSES, FILTERABLE_FLAGS, UPLOAD_ROLES, flagLabel } from './lib'
import type { BulkConfirmResult, TenderDocument } from './types'
import { useDebounced } from './useDebounced'

const PAGE_SIZE = 100
const fileName = (d: TenderDocument) => d.archive_path ?? d.original_filename

interface Failure {
  id: string
  error: string
}

function FilterSelect({
  id,
  label,
  value,
  onChange,
  children,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm text-ink">
        {label}
      </label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={controlClasses}>
        {children}
      </select>
    </div>
  )
}

export function TenderDocumentsTab({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canUpload = hasRole(...UPLOAD_ROLES)
  const canConfirm = hasRole(...CONFIRM_ROLES)

  const [packageId, setPackageId] = useState('')
  const [docClass, setDocClass] = useState('')
  const [status, setStatus] = useState('')
  const [flag, setFlag] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const q = useDebounced(search, 300)

  const { data: packages = [] } = useTenderPackages(projectId)
  const { data: classes = [] } = useTenderClasses()
  const docsQuery = useTenderDocuments(projectId, {
    package_id: packageId || undefined,
    doc_class: docClass || undefined,
    status: status || undefined,
    flag: flag || undefined,
    q: q || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })
  const rows = useMemo(() => docsQuery.data?.items ?? [], [docsQuery.data])

  const confirmDoc = useConfirmDocument(projectId)
  const exclude = useExclude(projectId)
  const rerun = useRerun(projectId)
  const reclassify = useReclassify(projectId)
  const editMeta = useEditMetadata(projectId)
  const bulk = useBulkConfirm(projectId)

  const gridApi = useRef<GridApi<TenderDocument> | null>(null)
  const [selectedRaw, setSelected] = useState<string[]>([])
  // Ignore selected ids that are no longer on the page (filters, paging, status change).
  const selected = useMemo(
    () => selectedRaw.filter((id) => rows.some((r) => r.id === id && r.status === 'proposed')),
    [selectedRaw, rows],
  )
  const [actionError, setActionError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [failures, setFailures] = useState<Failure[]>([])
  const [evidenceDoc, setEvidenceDoc] = useState<TenderDocument | null>(null)
  const [excludeDoc, setExcludeDoc] = useState<TenderDocument | null>(null)
  const [confirmHigh, setConfirmHigh] = useState(false)
  const [changeClassOpen, setChangeClassOpen] = useState(false)
  const [newClass, setNewClass] = useState('')

  const resetView = () => {
    setPage(1)
    setSelected([])
    gridApi.current?.deselectAll()
  }

  const msg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

  const handlers: GridHandlers = {
    onView: (d) => setEvidenceDoc(d),
    onConfirm: (d) => {
      setActionError(null)
      confirmDoc.mutate(d.id, { onError: (e) => setActionError(`Could not confirm ${fileName(d)}: ${msg(e)}`) })
    },
    onExclude: (d) => setExcludeDoc(d),
    onRerun: (d) => {
      setActionError(null)
      rerun.mutate(d.id, { onError: (e) => setActionError(`Could not re-run ${fileName(d)}: ${msg(e)}`) })
    },
    onReclassify: (d, code) => {
      setActionError(null)
      reclassify.mutate({ id: d.id, doc_class: code }, { onError: (e) => setActionError(`Could not change the class of ${fileName(d)}: ${msg(e)}`) })
    },
    onEdit: (d, field, value, rollback) => {
      setActionError(null)
      editMeta.mutate(
        { id: d.id, [field]: value },
        {
          onError: (e) => {
            rollback()
            setActionError(`Could not save ${field.replace('_', ' ')} for ${fileName(d)}: ${msg(e)}`)
          },
        },
      )
    },
  }
  // The grid keeps stable column defs, so give it a stable handler object.
  const handlersRef = useRef(handlers)
  useEffect(() => {
    handlersRef.current = handlers
  })
  const stableHandlers = useMemo<GridHandlers>(
    () => ({
      onView: (d) => handlersRef.current.onView(d),
      onConfirm: (d) => handlersRef.current.onConfirm(d),
      onExclude: (d) => handlersRef.current.onExclude(d),
      onRerun: (d) => handlersRef.current.onRerun(d),
      onReclassify: (d, c) => handlersRef.current.onReclassify(d, c),
      onEdit: (d, f, v, r) => handlersRef.current.onEdit(d, f, v, r),
    }),
    [],
  )

  const showBulkResult = (r: BulkConfirmResult) => {
    setStatusMsg(`Confirmed ${r.confirmed}, skipped ${r.skipped}, failed ${r.failed}`)
    setFailures(r.results.filter((x) => !x.ok && x.error && !x.error.startsWith('not proposed')).map((x) => ({ id: x.id, error: x.error as string })))
    setSelected([])
    gridApi.current?.deselectAll()
  }

  const runBulk = (body: Parameters<typeof bulk.mutate>[0]) => {
    setActionError(null)
    setStatusMsg(null)
    setFailures([])
    bulk.mutate(body, { onSuccess: showBulkResult, onError: (e) => setActionError(msg(e)) })
  }

  const applyClassToSelection = async () => {
    setChangeClassOpen(false)
    setActionError(null)
    setStatusMsg(null)
    const fails: Failure[] = []
    let ok = 0
    for (const id of selected) {
      try {
        await reclassify.mutateAsync({ id, doc_class: newClass })
        ok += 1
      } catch (e) {
        fails.push({ id, error: msg(e) })
      }
    }
    setStatusMsg(`Reclassified ${ok}, failed ${fails.length}`)
    setFailures(fails)
    setSelected([])
    gridApi.current?.deselectAll()
  }

  const nameFor = (id: string) => {
    const d = rows.find((r) => r.id === id)
    return d ? fileName(d) : id
  }

  const total = docsQuery.data?.total ?? 0
  const offset = docsQuery.data?.offset ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const isEmpty =
    packages.length === 0 && docsQuery.data?.total === 0 && !packageId && !docClass && !status && !flag && !q
  const selectedPackage = packages.find((p) => p.id === packageId)

  return (
    <div>
      {canUpload && isEmpty && (
        <div className="mt-6 rounded-card border-2 border-dashed border-brand bg-brand-subtle p-8 text-center">
          <h2 className="text-xl font-semibold text-ink">Drop the tender package here</h2>
          <p className="mx-auto mt-2 max-w-xl text-base text-ink-2">
            Drop a whole folder, several files or a .zip and the documents are sorted and classified for you to review.
          </p>
        </div>
      )}
      {canUpload && <UploadPanel projectId={projectId} onUploaded={(id) => { setPackageId(id); resetView() }} />}

      <Card className="mt-6">
        <SectionHeading>Tender documents</SectionHeading>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <FilterSelect id="tender-package" label="Package" value={packageId} onChange={(v) => { setPackageId(v); resetView() }}>
            <option value="">All packages</option>
            {packages.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label ?? 'Untitled package'} ({p.received_date}, {p.status})
              </option>
            ))}
          </FilterSelect>
          <FilterSelect id="tender-class" label="Class" value={docClass} onChange={(v) => { setDocClass(v); resetView() }}>
            <option value="">All classes</option>
            {classes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </FilterSelect>
          <FilterSelect id="tender-status" label="Status" value={status} onChange={(v) => { setStatus(v); resetView() }}>
            <option value="">All statuses</option>
            {DOC_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </FilterSelect>
          <FilterSelect id="tender-flag" label="Flag" value={flag} onChange={(v) => { setFlag(v); resetView() }}>
            <option value="">All flags</option>
            {FILTERABLE_FLAGS.map((f) => (
              <option key={f} value={f}>
                {flagLabel(f)}
              </option>
            ))}
          </FilterSelect>
          <div>
            <label htmlFor="tender-search" className="mb-1 block text-sm text-ink">
              Search documents
            </label>
            <input
              id="tender-search"
              type="search"
              value={search}
              onChange={(e) => { setSearch(e.target.value); resetView() }}
              className={controlClasses}
            />
          </div>
        </div>

        {canConfirm && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button onClick={() => setConfirmHigh(true)} loading={bulk.isPending}>
              Confirm high-confidence
            </Button>
            <Button variant="secondary" disabled={selected.length === 0 || bulk.isPending} onClick={() => runBulk({ document_ids: selected })}>
              Confirm selected ({selected.length})
            </Button>
            <Button
              variant="secondary"
              disabled={selected.length === 0}
              onClick={() => {
                setNewClass(classes[0]?.code ?? '')
                setChangeClassOpen(true)
              }}
            >
              Change class...
            </Button>
          </div>
        )}

        {statusMsg && (
          <p role="status" className="mt-3 text-sm text-ink">
            {statusMsg}
          </p>
        )}
        {failures.length > 0 && (
          <ul role="alert" className="mt-2 space-y-1 text-sm text-danger">
            {failures.map((f) => (
              <li key={f.id}>
                {nameFor(f.id)}: {f.error}
              </li>
            ))}
          </ul>
        )}
        {actionError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {actionError}
          </p>
        )}

        <div className="mt-4">
          {docsQuery.isLoading && <SkeletonRows count={6} />}
          {docsQuery.isError && (
            <p role="alert" className="text-sm text-danger">
              {docsQuery.error.message}
            </p>
          )}
          {docsQuery.data && rows.length === 0 && (
            <p className="text-base text-ink-2">No tender documents match. Upload a transmittal to get started.</p>
          )}
          {rows.length > 0 && (
            <ReviewGrid
              rows={rows}
              classes={classes}
              canConfirm={canConfirm}
              handlers={stableHandlers}
              onSelectionChange={setSelected}
              onGridReady={(api) => {
                gridApi.current = api
              }}
            />
          )}
        </div>
        {docsQuery.data && rows.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-2">
            <span>
              Showing {offset + 1} to {offset + rows.length} of {total}
            </span>
            <Pagination page={page} pageCount={pageCount} onPageChange={(p) => { setPage(p); setSelected([]) }} />
          </div>
        )}
      </Card>

      <AddendaRegister projectId={projectId} />
      <DocumentRegister projectId={projectId} />

      <EvidenceModal
        documentId={evidenceDoc?.id ?? null}
        filename={evidenceDoc ? fileName(evidenceDoc) : ''}
        classes={classes}
        onClose={() => setEvidenceDoc(null)}
      />
      <TextPromptModal
        open={excludeDoc !== null}
        title={excludeDoc ? `Exclude ${fileName(excludeDoc)}?` : 'Exclude'}
        message="Say why this file should be left out of the project. It will not be routed."
        submitLabel="Exclude"
        onCancel={() => setExcludeDoc(null)}
        onSubmit={(reason) => {
          const d = excludeDoc
          setExcludeDoc(null)
          if (!d) return
          setActionError(null)
          exclude.mutate({ id: d.id, reason }, { onError: (e) => setActionError(`Could not exclude ${fileName(d)}: ${msg(e)}`) })
        }}
      />
      <ConfirmModal
        open={confirmHigh}
        title="Confirm high-confidence proposals?"
        message={`Confirm every proposal at 85% or more with no conflict, low-confidence or duplicate flag in ${
          selectedPackage ? (selectedPackage.label ?? 'the selected package') : 'all packages'
        }? Everything else stays for one-by-one review.`}
        confirmLabel="Confirm all"
        onCancel={() => setConfirmHigh(false)}
        onConfirm={() => {
          setConfirmHigh(false)
          runBulk(packageId ? { package_id: packageId } : {})
        }}
      />
      <Modal open={changeClassOpen} title="Change class" onClose={() => setChangeClassOpen(false)}>
        <div className="mt-3">
          <label htmlFor="tender-new-class" className="mb-1 block text-sm text-ink">
            New class for {selected.length} selected {selected.length === 1 ? 'document' : 'documents'}
          </label>
          <select id="tender-new-class" value={newClass} onChange={(e) => setNewClass(e.target.value)} className={controlClasses}>
            {classes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setChangeClassOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" disabled={!newClass} onClick={applyClassToSelection}>
            Apply class
          </Button>
        </div>
      </Modal>
    </div>
  )
}
