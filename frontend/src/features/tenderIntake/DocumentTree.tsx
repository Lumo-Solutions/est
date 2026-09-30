import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { controlClasses } from '../../components/Field'
import { TextPromptModal } from '../../components/TextPromptModal'
import { ChangeClassDialog } from './ChangeClassDialog'
import { EMPTY_CHOICE, type ChoiceBody, type ClassChoice } from './classChoice'
import { DocumentRow, type RowActions } from './DocumentRow'
import { EvidenceModal } from './EvidenceModal'
import { useBulkReclassify, useExclude, useReclassifyDocument, useRerun, useTenderClasses } from './api'
import {
  DECIDED_BY_OPTIONS,
  DISPLAY_STATUSES,
  GROUP_PAGE_SIZE,
  NOT_CLASSIFIED_LABEL,
  NO_CLASS_FILTER,
  NO_FILTERS,
  classLabeler,
  classOptions,
  defaultExpanded,
  displayStatusLabel,
  filterItems,
  groupByFolder,
  groupByType,
  isFiltering,
  type GroupMode,
  type TreeFilters,
  type TreeNode,
} from './treeLib'
import type { TreeItem } from './types'

const BULK_MAX = 1000
const msg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

function FilterSelect({ id, label, value, onChange, children }: { id: string; label: string; value: string; onChange: (v: string) => void; children: React.ReactNode }) {
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

// Tri-state checkbox for a group header: every file, some files, or none selected.
function GroupCheckbox({ label, ids, selected, onToggle }: { label: string; ids: string[]; selected: ReadonlySet<string>; onToggle: (ids: string[], on: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const n = ids.reduce((c, id) => c + (selected.has(id) ? 1 : 0), 0)
  const all = ids.length > 0 && n === ids.length
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = n > 0 && !all
  }, [n, all])
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={all}
      onChange={(e) => onToggle(ids, e.target.checked)}
      className="h-4 w-4 shrink-0 accent-brand"
    />
  )
}

interface Pending {
  targets: TreeItem[]
  body: ChoiceBody
  bulk: boolean
}

// The organised document tree: every file grouped by type (class, then discipline and drawing type
// for drawings) or by the folders it was uploaded in, with search, filters, row actions and bulk
// change-class. Collapsed groups render nothing and long groups page in 100 at a time, so a
// 300-file tender stays responsive.
export function DocumentTree({ projectId, items, canConfirm }: { projectId: string; items: TreeItem[]; canConfirm: boolean }) {
  const { data: classes = [] } = useTenderClasses()
  const reclassify = useReclassifyDocument(projectId)
  const bulkReclassify = useBulkReclassify(projectId)
  const exclude = useExclude(projectId)
  const rerun = useRerun(projectId)

  const [mode, setMode] = useState<GroupMode>('type')
  const [filters, setFilters] = useState<TreeFilters>(NO_FILTERS)
  const [openOverride, setOpenOverride] = useState<Record<string, boolean>>({})
  const [limits, setLimits] = useState<Record<string, number>>({})
  const [selectedRaw, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [evidenceItem, setEvidenceItem] = useState<TreeItem | null>(null)
  const [excludeItem, setExcludeItem] = useState<TreeItem | null>(null)
  const [changeTargets, setChangeTargets] = useState<{ items: TreeItem[]; bulk: boolean } | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [failures, setFailures] = useState<string[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)

  const classLabel = useMemo(() => classLabeler(classes), [classes])
  const options = useMemo(() => classOptions(classes), [classes])
  const filtering = isFiltering(filters)
  const visible = useMemo(() => filterItems(items, filters), [items, filters])
  const nodes = useMemo(() => (mode === 'type' ? groupByType(visible, classLabel) : groupByFolder(visible)), [mode, visible, classLabel])
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])
  // Ignore selected ids that are filtered out or gone (a poll or reclassify moved them).
  const visibleIds = useMemo(() => new Set(visible.map((i) => i.id)), [visible])
  const selected = useMemo(() => new Set([...selectedRaw].filter((id) => visibleIds.has(id))), [selectedRaw, visibleIds])

  const setFilter = (patch: Partial<TreeFilters>) => setFilters((f) => ({ ...f, ...patch }))
  const isOpen = (n: TreeNode) => openOverride[n.key] ?? defaultExpanded(n, mode, { filtering, total: items.length })

  const toggleIds = useCallback((ids: string[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      for (const id of ids) {
        if (on) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }, [])

  const handlers = {
    onSelect: (id: string, on: boolean) => toggleIds([id], on),
    onView: (item: TreeItem) => setEvidenceItem(item),
    onChange: (item: TreeItem) => setChangeTargets({ items: [item], bulk: false }),
    onExclude: (item: TreeItem) => setExcludeItem(item),
    onRerun: (item: TreeItem) => {
      setActionError(null)
      rerun.mutate(item.id, { onError: (e) => setActionError(`Could not re-run ${item.name}: ${msg(e)}`) })
    },
  }
  // Rows are memoised, so they get one stable actions object that calls the latest handlers.
  const latest = useRef(handlers)
  useEffect(() => {
    latest.current = handlers
  })
  const actions = useMemo<RowActions>(
    () => ({
      onSelect: (id, on) => latest.current.onSelect(id, on),
      onView: (i) => latest.current.onView(i),
      onChange: (i) => latest.current.onChange(i),
      onExclude: (i) => latest.current.onExclude(i),
      onRerun: (i) => latest.current.onRerun(i),
    }),
    [],
  )

  const runChange = async ({ targets, body, bulk }: Pending) => {
    setActionError(null)
    setStatusMsg(null)
    setFailures([])
    if (!bulk) {
      const item = targets[0]
      reclassify.mutate(
        { id: item.id, ...body, confirm: true },
        { onError: (e) => setActionError(`Could not change the class of ${item.name}: ${msg(e)}`) },
      )
      return
    }
    setBulkBusy(true)
    let confirmed = 0
    let failed = 0
    let skipped = 0
    const fails: string[] = []
    const ids = targets.map((t) => t.id)
    try {
      for (let i = 0; i < ids.length; i += BULK_MAX) {
        const r = await bulkReclassify.mutateAsync({ document_ids: ids.slice(i, i + BULK_MAX), ...body, confirm: true })
        confirmed += r.confirmed
        failed += r.failed
        skipped += r.skipped
        for (const x of r.results) if (!x.ok && x.error) fails.push(`${byId.get(x.id)?.name ?? x.id}: ${x.error}`)
      }
    } catch (e) {
      fails.push(msg(e))
    } finally {
      setBulkBusy(false)
    }
    setStatusMsg(`Changed ${confirmed}, failed ${failed}${skipped > 0 ? `, skipped ${skipped}` : ''}`)
    setFailures(fails)
    setSelected(new Set())
  }

  // A routed drawing that stops being a drawing leaves the takeoff: ask first.
  const applyChange = (body: ChoiceBody) => {
    if (!changeTargets) return
    const next: Pending = { targets: changeTargets.items, body, bulk: changeTargets.bulk }
    setChangeTargets(null)
    const leaving = next.targets.filter((t) => t.routed_kind === 'drawing' && body.doc_class !== 'drawing')
    if (leaving.length > 0) setPending(next)
    else void runChange(next)
  }

  const leavingCount = pending ? pending.targets.filter((t) => t.routed_kind === 'drawing').length : 0
  const only = changeTargets && changeTargets.items.length === 1 ? changeTargets.items[0] : null
  const initial: ClassChoice = only
    ? { doc_class: only.doc_class ?? '', discipline: only.discipline ?? '', drawing_type: only.drawing_type ?? '' }
    : EMPTY_CHOICE

  const renderNode = (node: TreeNode): React.ReactNode => {
    const open = isOpen(node)
    const limit = limits[node.key] ?? GROUP_PAGE_SIZE
    const shown = node.items.slice(0, limit)
    const hidden = node.items.length - shown.length
    return (
      <div key={node.key} role="group" aria-label={`${node.label}, ${node.count} ${node.count === 1 ? 'file' : 'files'}`}>
        <div className="flex items-center gap-2 py-1.5">
          {canConfirm && (
            <GroupCheckbox label={`Select all ${node.count} in ${node.label}`} ids={node.ids} selected={selected} onToggle={toggleIds} />
          )}
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpenOverride((o) => ({ ...o, [node.key]: !open }))}
            className="flex min-w-0 flex-1 items-center gap-2 rounded px-1 text-left text-sm font-semibold text-ink-title hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            <span aria-hidden="true" className="w-3 shrink-0 text-ink-2">
              {open ? '▾' : '▸'}
            </span>
            <span className="truncate">{node.label}</span>
            <span className="shrink-0 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium tabular-nums text-ink-2">{node.count}</span>
          </button>
        </div>
        {open && (
          <div className="ml-2 border-l border-row-rule pl-3">
            {node.children.map(renderNode)}
            {shown.length > 0 && (
              <ul aria-label={`${node.label} files`} className="divide-y divide-row-rule">
                {shown.map((item) => (
                  <DocumentRow key={item.id} item={item} canAct={canConfirm} selected={selected.has(item.id)} showFolder={mode === 'type'} actions={actions} />
                ))}
              </ul>
            )}
            {hidden > 0 && (
              <div className="py-2">
                <Button variant="secondary" size="sm" onClick={() => setLimits((l) => ({ ...l, [node.key]: limit + GROUP_PAGE_SIZE }))}>
                  Show {Math.min(hidden, GROUP_PAGE_SIZE)} more ({hidden} not shown)
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  const modeButton = (value: GroupMode, label: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      onClick={() => setMode(value)}
      className={`px-4 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
        mode === value ? 'bg-brand text-white' : 'bg-white text-brand hover:bg-brand-subtle'
      }`}
    >
      {label}
    </button>
  )

  return (
    <Card className="mt-6">
      <SectionHeading
        action={
          <div role="group" aria-label="Group documents" className="inline-flex overflow-hidden rounded-pill border border-brand">
            {modeButton('type', 'By document type')}
            {modeButton('folder', 'Original folders')}
          </div>
        }
      >
        Project documents
      </SectionHeading>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <label htmlFor="tree-search" className="mb-1 block text-sm text-ink">
            Search documents
          </label>
          <input
            id="tree-search"
            type="search"
            value={filters.q}
            onChange={(e) => setFilter({ q: e.target.value })}
            placeholder="Name, folder, number or title"
            className={controlClasses}
          />
        </div>
        <FilterSelect id="tree-class" label="Class" value={filters.docClass} onChange={(v) => setFilter({ docClass: v })}>
          <option value="">All classes</option>
          {options.map((c) => (
            <option key={c.code} value={c.code}>
              {c.label}
            </option>
          ))}
          <option value={NO_CLASS_FILTER}>{NOT_CLASSIFIED_LABEL}</option>
        </FilterSelect>
        <FilterSelect id="tree-status" label="Status" value={filters.status} onChange={(v) => setFilter({ status: v })}>
          <option value="">All statuses</option>
          {DISPLAY_STATUSES.map((s) => (
            <option key={s} value={s}>
              {displayStatusLabel(s)}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect id="tree-decided" label="Decided by" value={filters.decidedBy} onChange={(v) => setFilter({ decidedBy: v })}>
          <option value="">Anyone</option>
          {DECIDED_BY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </FilterSelect>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p aria-live="polite" className="text-sm text-ink-2">
          {filtering ? `${visible.length} of ${items.length} files match` : `${items.length} ${items.length === 1 ? 'file' : 'files'}`}
        </p>
        {filtering && (
          <Button variant="secondary" size="sm" onClick={() => setFilters(NO_FILTERS)}>
            Clear filters
          </Button>
        )}
      </div>

      {canConfirm && selected.size > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-card bg-brand-subtle px-4 py-2">
          <span className="text-sm font-medium text-ink">{selected.size} selected</span>
          <Button
            size="sm"
            loading={bulkBusy}
            onClick={() => setChangeTargets({ items: [...selected].map((id) => byId.get(id)).filter((i): i is TreeItem => Boolean(i)), bulk: true })}
          >
            Change class for {selected.size} {selected.size === 1 ? 'file' : 'files'}
          </Button>
          <Button variant="secondary" size="sm" disabled={bulkBusy} onClick={() => setSelected(new Set())}>
            Clear selection
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
          {failures.map((f, i) => (
            <li key={`${i}-${f}`}>{f}</li>
          ))}
        </ul>
      )}
      {actionError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {actionError}
        </p>
      )}

      <div className="mt-3">
        {visible.length === 0 ? (
          <p className="py-4 text-base text-ink-2">{filtering ? 'No files match your search or filters.' : 'No documents yet.'}</p>
        ) : (
          nodes.map(renderNode)
        )}
      </div>

      <EvidenceModal
        documentId={evidenceItem?.id ?? null}
        filename={evidenceItem?.name ?? ''}
        classes={classes}
        onClose={() => setEvidenceItem(null)}
      />
      <ChangeClassDialog
        open={changeTargets !== null}
        title={only ? `Change class of ${only.name}` : 'Change class'}
        description={
          only
            ? 'The file is sorted under the new class straight away.'
            : `New class for ${changeTargets?.items.length ?? 0} selected files. They are sorted under it straight away.`
        }
        options={options}
        initial={initial}
        onCancel={() => setChangeTargets(null)}
        onApply={applyChange}
      />
      <ConfirmModal
        open={pending !== null}
        title="Take this out of the takeoff?"
        message={`${leavingCount} ${leavingCount === 1 ? 'drawing leaves' : 'drawings leave'} the takeoff. Their measurements are archived, not deleted.`}
        confirmLabel="Change class"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const p = pending
          setPending(null)
          if (p) void runChange(p)
        }}
      />
      <TextPromptModal
        open={excludeItem !== null}
        title={excludeItem ? `Exclude ${excludeItem.name}?` : 'Exclude'}
        message="Say why this file should be left out of the project. It will not be routed."
        submitLabel="Exclude"
        onCancel={() => setExcludeItem(null)}
        onSubmit={(reason) => {
          const item = excludeItem
          setExcludeItem(null)
          if (!item) return
          setActionError(null)
          exclude.mutate({ id: item.id, reason }, { onError: (e) => setActionError(`Could not exclude ${item.name}: ${msg(e)}`) })
        }}
      />
    </Card>
  )
}
