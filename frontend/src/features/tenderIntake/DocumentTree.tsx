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
import { useBulkReclassify, useExclude, useInvalidateIntake, useReclassifyDocument, useRerun, useTenderClasses, useTenderItems } from './api'
import {
  DECIDED_BY_OPTIONS,
  DISPLAY_STATUSES,
  NOT_CLASSIFIED_LABEL,
  NO_CLASS_FILTER,
  NO_FILTERS,
  buildFolderNodes,
  buildTypeNodes,
  capList,
  classLabeler,
  classOptions,
  defaultExpanded,
  displayStatusLabel,
  isFiltering,
  toDocFilter,
  type GroupMode,
  type TreeFilters,
  type TreeNode,
} from './treeLib'
import type { DocFilter, FolderCount, GroupCount, TreeItem, TreeSummary } from './types'
import { useDebounced } from './useDebounced'
import { VirtualRows } from './VirtualRows'

const BULK_MAX = 1000
const SEARCH_DEBOUNCE_MS = 250
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

/** A whole group (or every match of the filters), selected server-side: only its filter and count are kept. */
interface GroupSelection {
  key: string
  label: string
  filter: DocFilter
  count: number
  classHint: string
}

type ChangeTarget =
  | { kind: 'single'; item: TreeItem }
  | { kind: 'ids'; items: TreeItem[] }
  | { kind: 'group'; group: GroupSelection }

interface Pending {
  target: ChangeTarget
  body: ChoiceBody
}

type ItemsQuery = ReturnType<typeof useTenderItems>

// The pages of one server-side list in a virtualised, scrollable box.
function ItemPages({
  query,
  label,
  canAct,
  selected,
  showFolder,
  actions,
}: {
  query: ItemsQuery
  label: string
  canAct: boolean
  selected: ReadonlySet<string>
  showFolder: boolean
  actions: RowActions
}) {
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])
  const total = query.data?.pages[0]?.total ?? 0
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  if (query.isError) {
    return (
      <p role="alert" className="py-2 text-sm text-danger">
        {msg(query.error)}
      </p>
    )
  }
  if (query.isLoading) return <p className="py-2 text-sm text-ink-2">Loading files...</p>
  if (items.length === 0) return null
  return (
    <VirtualRows
      label={label}
      items={items}
      total={total}
      hasMore={Boolean(hasNextPage)}
      loadingMore={isFetchingNextPage}
      onLoadMore={loadMore}
      getKey={(i) => i.id}
      renderRow={(item) => <DocumentRow item={item} canAct={canAct} selected={selected.has(item.id)} showFolder={showFolder} actions={actions} />}
    />
  )
}

// Mounted only while its group is open, so a collapsed group costs nothing and an open one fetches its own files.
function GroupFiles({ projectId, node, ...rest }: { projectId: string; node: TreeNode; canAct: boolean; selected: ReadonlySet<string>; showFolder: boolean; actions: RowActions }) {
  const query = useTenderItems(projectId, node.listFilter)
  return <ItemPages query={query} label={`${node.label} files`} {...rest} />
}

// The organised document tree. The server sends counts only: groups are built from them, a group fetches its own
// files (100 a page, virtualised) when opened, and search and the filters run server-side as one flat list.
export function DocumentTree({
  projectId,
  summary,
  groups,
  folders,
  canConfirm,
}: {
  projectId: string
  summary: TreeSummary
  groups: GroupCount[]
  folders: FolderCount[]
  canConfirm: boolean
}) {
  const { data: classes = [] } = useTenderClasses()
  const reclassify = useReclassifyDocument(projectId)
  const bulkReclassify = useBulkReclassify(projectId, { quiet: true })
  const invalidateIntake = useInvalidateIntake(projectId)
  const exclude = useExclude(projectId)
  const rerun = useRerun(projectId)

  const [mode, setMode] = useState<GroupMode>('type')
  const [typed, setTyped] = useState<TreeFilters>(NO_FILTERS)
  const [openOverride, setOpenOverride] = useState<Record<string, boolean>>({})
  const [selectedItems, setSelectedItems] = useState<ReadonlyMap<string, TreeItem>>(new Map())
  const [groupSel, setGroupSel] = useState<GroupSelection | null>(null)
  const [evidenceItem, setEvidenceItem] = useState<TreeItem | null>(null)
  const [excludeItem, setExcludeItem] = useState<TreeItem | null>(null)
  const [changeTarget, setChangeTarget] = useState<ChangeTarget | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [failures, setFailures] = useState<string[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const [progress, setProgress] = useState<{ changed: number; total: number } | null>(null)
  const cancelRef = useRef(false)

  // The search box applies after a short pause; the selects apply at once.
  const debouncedQ = useDebounced(typed.q, SEARCH_DEBOUNCE_MS)
  const appliedQ = typed.q.trim() === '' ? '' : debouncedQ
  const filters = useMemo<TreeFilters>(() => ({ ...typed, q: appliedQ }), [typed, appliedQ])
  const filtering = isFiltering(filters)
  const serverFilter = useMemo(() => toDocFilter(filters), [filters])
  const flat = useTenderItems(projectId, serverFilter, { enabled: filtering })
  const flatTotal = flat.data?.pages[0]?.total

  const classLabel = useMemo(() => classLabeler(classes), [classes])
  const options = useMemo(() => classOptions(classes), [classes])
  const nodes = useMemo(() => (mode === 'type' ? buildTypeNodes(groups, classLabel) : buildFolderNodes(folders)), [mode, groups, folders, classLabel])
  const selectedIds = useMemo(() => new Set(selectedItems.keys()), [selectedItems])

  const setFilter = (patch: Partial<TreeFilters>) => setTyped((f) => ({ ...f, ...patch }))
  const isOpen = (n: TreeNode) => openOverride[n.key] ?? defaultExpanded(n, mode, { total: summary.total })

  const toggleItem = useCallback((item: TreeItem, on: boolean) => {
    setGroupSel(null)
    setSelectedItems((prev) => {
      const next = new Map(prev)
      if (on) next.set(item.id, item)
      else next.delete(item.id)
      return next
    })
  }, [])
  const toggleGroup = (sel: GroupSelection, on: boolean) => {
    setSelectedItems(new Map())
    setGroupSel(on ? sel : null)
  }
  const clearSelection = () => {
    setSelectedItems(new Map())
    setGroupSel(null)
  }

  const handlers = {
    onSelect: toggleItem,
    onView: (item: TreeItem) => setEvidenceItem(item),
    onChange: (item: TreeItem) => setChangeTarget({ kind: 'single', item }),
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
      onSelect: (i, on) => latest.current.onSelect(i, on),
      onView: (i) => latest.current.onView(i),
      onChange: (i) => latest.current.onChange(i),
      onExclude: (i) => latest.current.onExclude(i),
      onRerun: (i) => latest.current.onRerun(i),
    }),
    [],
  )

  // Bulk change of class: chunks of ids, or a cursor loop over a whole group, stoppable after the current chunk.
  const runBulk = async (target: Exclude<ChangeTarget, { kind: 'single' }>, body: ChoiceBody) => {
    setActionError(null)
    setStatusMsg(null)
    setFailures([])
    setBulkBusy(true)
    cancelRef.current = false
    const names = new Map<string, string>(target.kind === 'ids' ? target.items.map((i) => [i.id, i.name]) : [])
    let total = target.kind === 'ids' ? target.items.length : target.group.count
    let changed = 0
    let failed = 0
    let skipped = 0
    let stopped = false
    const fails: string[] = []
    setProgress({ changed, total })
    const tally = (r: Awaited<ReturnType<typeof bulkReclassify.mutateAsync>>) => {
      changed += r.confirmed
      failed += r.failed
      skipped += r.skipped
      for (const x of r.results) if (!x.ok && x.error) fails.push(`${names.get(x.id) ?? x.id}: ${x.error}`)
      setProgress({ changed, total })
    }
    try {
      if (target.kind === 'ids') {
        const ids = target.items.map((t) => t.id)
        for (let i = 0; i < ids.length; i += BULK_MAX) {
          if (cancelRef.current) {
            stopped = true
            break
          }
          tally(await bulkReclassify.mutateAsync({ document_ids: ids.slice(i, i + BULK_MAX), ...body, confirm: true }))
        }
      } else {
        let cursor: string | null = null
        let first = true
        do {
          if (cancelRef.current) {
            stopped = true
            break
          }
          const r: Awaited<ReturnType<typeof bulkReclassify.mutateAsync>> = await bulkReclassify.mutateAsync({ filter: target.group.filter, cursor, ...body, confirm: true })
          if (first && r.matched != null) total = r.matched
          first = false
          tally(r)
          const next: string | null = r.next_cursor ?? null
          if (next === cursor) break
          cursor = next
        } while (cursor)
      }
    } catch (e) {
      fails.push(msg(e))
    } finally {
      setBulkBusy(false)
      setProgress(null)
      invalidateIntake()
    }
    setStatusMsg(
      `Changed ${changed} of ${total}${failed > 0 ? `, failed ${failed}` : ''}${skipped > 0 ? `, skipped ${skipped}` : ''}${stopped ? '. Stopped before the rest.' : ''}`,
    )
    setFailures(fails)
    clearSelection()
  }

  const runChange = ({ target, body }: Pending) => {
    if (target.kind === 'single') {
      setActionError(null)
      setStatusMsg(null)
      setFailures([])
      reclassify.mutate(
        { id: target.item.id, ...body, confirm: true },
        { onError: (e) => setActionError(`Could not change the class of ${target.item.name}: ${msg(e)}`) },
      )
      return
    }
    void runBulk(target, body)
  }

  // A routed drawing that stops being a drawing leaves the takeoff: ask first. For a whole group the server decides
  // which files those are, so ask whenever the group could hold drawings.
  const leavesDrawings = (target: ChangeTarget, body: ChoiceBody): boolean => {
    if (body.doc_class === 'drawing') return false
    if (target.kind === 'single') return target.item.routed_kind === 'drawing'
    if (target.kind === 'ids') return target.items.some((t) => t.routed_kind === 'drawing')
    return target.group.classHint === 'drawing' || target.group.classHint === 'mixed'
  }
  const applyChange = (body: ChoiceBody) => {
    if (!changeTarget) return
    const next: Pending = { target: changeTarget, body }
    setChangeTarget(null)
    if (leavesDrawings(changeTarget, body)) setPending(next)
    else runChange(next)
  }

  const pendingMessage = (p: Pending): string => {
    if (p.target.kind === 'group') {
      return `Some of the ${p.target.group.count} files in ${p.target.group.label} may be drawings. Any drawing leaves the takeoff. Their measurements are archived, not deleted.`
    }
    const n = p.target.kind === 'single' ? 1 : p.target.items.filter((t) => t.routed_kind === 'drawing').length
    return `${n} ${n === 1 ? 'drawing leaves' : 'drawings leave'} the takeoff. Their measurements are archived, not deleted.`
  }

  const only = changeTarget?.kind === 'single' ? changeTarget.item : null
  const targetCount = !changeTarget ? 0 : changeTarget.kind === 'single' ? 1 : changeTarget.kind === 'ids' ? changeTarget.items.length : changeTarget.group.count
  const initial: ClassChoice = only
    ? { doc_class: only.doc_class ?? '', discipline: only.discipline ?? '', drawing_type: only.drawing_type ?? '' }
    : EMPTY_CHOICE

  const startChangeSelected = () => {
    if (groupSel) setChangeTarget({ kind: 'group', group: groupSel })
    else setChangeTarget({ kind: 'ids', items: [...selectedItems.values()] })
  }
  const selectedCount = groupSel ? groupSel.count : selectedItems.size

  const renderNode = (node: TreeNode): React.ReactNode => {
    const open = isOpen(node)
    return (
      <div key={node.key} role="group" aria-label={`${node.label}, ${node.count} ${node.count === 1 ? 'file' : 'files'}`}>
        <div className="flex items-center gap-2 py-1.5">
          {canConfirm && (
            <input
              type="checkbox"
              aria-label={`Select all ${node.count} in ${node.label}`}
              checked={groupSel?.key === node.key}
              onChange={(e) =>
                toggleGroup({ key: node.key, label: node.label, filter: node.selectFilter, count: node.count, classHint: node.classHint }, e.target.checked)
              }
              className="h-4 w-4 shrink-0 accent-brand"
            />
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
            {node.listFilter && (
              <GroupFiles projectId={projectId} node={node} canAct={canConfirm} selected={selectedIds} showFolder={mode === 'type'} actions={actions} />
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

  const failureView = capList(failures, 20)
  const matchLabel = `${flatTotal ?? 0} ${flatTotal === 1 ? 'file matches' : 'files match'}`

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
            value={typed.q}
            onChange={(e) => setFilter({ q: e.target.value })}
            placeholder="Name, folder, number or title"
            className={controlClasses}
          />
        </div>
        <FilterSelect id="tree-class" label="Class" value={typed.docClass} onChange={(v) => setFilter({ docClass: v })}>
          <option value="">All classes</option>
          {options.map((c) => (
            <option key={c.code} value={c.code}>
              {c.label}
            </option>
          ))}
          <option value={NO_CLASS_FILTER}>{NOT_CLASSIFIED_LABEL}</option>
        </FilterSelect>
        <FilterSelect id="tree-status" label="Status" value={typed.status} onChange={(v) => setFilter({ status: v })}>
          <option value="">All statuses</option>
          {DISPLAY_STATUSES.map((s) => (
            <option key={s} value={s}>
              {displayStatusLabel(s)}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect id="tree-decided" label="Decided by" value={typed.decidedBy} onChange={(v) => setFilter({ decidedBy: v })}>
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
          {filtering
            ? flatTotal === undefined
              ? 'Searching...'
              : matchLabel
            : `${summary.total} ${summary.total === 1 ? 'file' : 'files'}`}
        </p>
        {isFiltering(typed) && (
          <Button variant="secondary" size="sm" onClick={() => setTyped(NO_FILTERS)}>
            Clear filters
          </Button>
        )}
      </div>

      {canConfirm && selectedCount > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-card bg-brand-subtle px-4 py-2">
          <span className="text-sm font-medium text-ink">
            {groupSel ? `All ${groupSel.count} in ${groupSel.label} selected` : `${selectedCount} selected`}
          </span>
          <Button size="sm" loading={bulkBusy} onClick={startChangeSelected}>
            Change class for {selectedCount} {selectedCount === 1 ? 'file' : 'files'}
          </Button>
          <Button variant="secondary" size="sm" disabled={bulkBusy} onClick={clearSelection}>
            Clear selection
          </Button>
        </div>
      )}
      {progress && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="status" className="text-sm text-ink">
            Changed {progress.changed} of {progress.total}
          </p>
          <Button variant="secondary" size="sm" onClick={() => (cancelRef.current = true)}>
            Cancel
          </Button>
        </div>
      )}
      {statusMsg && (
        <p role="status" className="mt-3 text-sm text-ink">
          {statusMsg}
        </p>
      )}
      {failureView.shown.length > 0 && (
        <ul role="alert" className="mt-2 space-y-1 text-sm text-danger">
          {failureView.shown.map((f, i) => (
            <li key={`${i}-${f}`}>{f}</li>
          ))}
          {failureView.more > 0 && <li>and {failureView.more} more</li>}
        </ul>
      )}
      {actionError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {actionError}
        </p>
      )}

      <div className="mt-3">
        {filtering ? (
          <>
            {canConfirm && flatTotal !== undefined && flatTotal > 0 && (
              <label className="mb-2 flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={groupSel?.key === 'filtered'}
                  onChange={(e) => toggleGroup({ key: 'filtered', label: 'the matching files', filter: serverFilter, count: flatTotal, classHint: 'mixed' }, e.target.checked)}
                  className="h-4 w-4 shrink-0 accent-brand"
                />
                Select all {flatTotal} matching files
              </label>
            )}
            <ItemPages query={flat} label="Matching files" canAct={canConfirm} selected={selectedIds} showFolder actions={actions} />
            {flatTotal === 0 && <p className="py-4 text-base text-ink-2">No files match your search or filters.</p>}
          </>
        ) : nodes.length === 0 ? (
          <p className="py-4 text-base text-ink-2">No documents yet.</p>
        ) : (
          nodes.map(renderNode)
        )}
      </div>

      <EvidenceModal documentId={evidenceItem?.id ?? null} filename={evidenceItem?.name ?? ''} classes={classes} onClose={() => setEvidenceItem(null)} />
      <ChangeClassDialog
        open={changeTarget !== null}
        title={only ? `Change class of ${only.name}` : 'Change class'}
        description={
          only
            ? 'The file is sorted under the new class straight away.'
            : `New class for ${targetCount} selected files. They are sorted under it straight away.`
        }
        options={options}
        initial={initial}
        onCancel={() => setChangeTarget(null)}
        onApply={applyChange}
      />
      <ConfirmModal
        open={pending !== null}
        title="Take this out of the takeoff?"
        message={pending ? pendingMessage(pending) : ''}
        confirmLabel="Change class"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const p = pending
          setPending(null)
          if (p) runChange(p)
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
