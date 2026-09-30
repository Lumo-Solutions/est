import type { BadgeTone } from '../../components/Badge'
import {
  CLASS_ORDER,
  DEFAULT_CLASS_LABELS,
  DRAWING_DISCIPLINES,
  DRAWING_TYPES,
  LEGACY_DISCIPLINES,
  disciplineLabel,
  drawingTypeLabel,
  humanize,
} from './lib'
import type { TenderClass, TreeItem, TreeSummary } from './types'

// Pure logic for the project document tree: grouping, folder tree, filtering, labels.

export type GroupMode = 'type' | 'folder'

export interface TreeNode {
  key: string
  label: string
  depth: number
  /** Files directly in this group (leaf groups). */
  items: TreeItem[]
  children: TreeNode[]
  /** Files in this group and everything below it. */
  count: number
  /** Ids of every file in this group and below (for the group checkbox). */
  ids: string[]
}

export const NOT_CLASSIFIED_LABEL = 'Not classified yet'
export const NO_CLASS_FILTER = 'none'

// ---------------------------------------------------------------- status and decided-by

export const DISPLAY_STATUSES = [
  'queued',
  'reading',
  'classified',
  'extracting',
  'ready',
  'needs_check',
  'failed',
  'excluded',
] as const

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  reading: 'Reading',
  classified: 'Classified',
  extracting: 'Extracting',
  ready: 'Ready',
  needs_check: 'Needs check',
  failed: 'Failed',
  excluded: 'Excluded',
}

const STATUS_TONE: Record<string, BadgeTone> = {
  queued: 'neutral',
  reading: 'info',
  classified: 'info',
  extracting: 'info',
  ready: 'success',
  needs_check: 'warning',
  failed: 'danger',
  excluded: 'neutral',
}

export const displayStatusLabel = (s: string) => STATUS_LABEL[s] ?? humanize(s)
export const displayStatusTone = (s: string): BadgeTone => STATUS_TONE[s] ?? 'neutral'

export type DecidedBy = 'ai' | 'rules' | 'user'

export const DECIDED_BY_OPTIONS: { value: DecidedBy; label: string }[] = [
  { value: 'ai', label: 'AI' },
  { value: 'rules', label: 'Rules' },
  { value: 'user', label: 'You' },
]

/** Who decided the class. A rules fallback shows as rules even before anyone decided. */
export function decidedByInfo(item: TreeItem): { key: DecidedBy; label: string; tone: BadgeTone } | null {
  if (item.decided_by === 'user') return { key: 'user', label: 'You', tone: 'success' }
  if (item.decided_by === 'ai') {
    return { key: 'ai', label: item.auto_accepted ? 'AI (auto-accepted)' : 'AI', tone: 'info' }
  }
  if (item.decided_by === 'rules' || item.flags.includes('rules_fallback')) {
    return { key: 'rules', label: 'Classified by rules', tone: 'neutral' }
  }
  return null
}

const FLAG_TONE: Record<string, BadgeTone> = {
  conflict: 'danger',
  injection_suspected: 'danger',
  low_confidence: 'warning',
  duplicate: 'neutral',
  revision_of: 'info',
}

// rules_fallback is shown by the decided-by badge, so it is not repeated as a flag.
const HIDDEN_FLAGS = new Set(['rules_fallback'])

export function visibleFlags(item: TreeItem): { flag: string; tone: BadgeTone }[] {
  return item.flags.filter((f) => !HIDDEN_FLAGS.has(f)).map((flag) => ({ flag, tone: FLAG_TONE[flag] ?? 'neutral' }))
}

/** "Confirm all shown" skips files whose class needs a person's eyes. */
export const isBulkConfirmable = (item: TreeItem) =>
  !item.flags.includes('conflict') && !item.flags.includes('injection_suspected')

export function formatUnitType(u: string): string {
  const m = /^type[\s_-]*(\d+)$/i.exec(u.trim())
  return m ? `Type ${m[1]}` : humanize(u.trim())
}

// ---------------------------------------------------------------- classes

export interface ClassOption {
  code: string
  label: string
}

/** Enabled classes in the standard order; falls back to the defaults while the tenant list loads. */
export function classOptions(classes: TenderClass[]): ClassOption[] {
  const source: ClassOption[] =
    classes.length > 0
      ? classes.filter((c) => c.enabled).map((c) => ({ code: c.code, label: c.label }))
      : CLASS_ORDER.map((code) => ({ code, label: DEFAULT_CLASS_LABELS[code] }))
  const rank = (code: string) => {
    const i = CLASS_ORDER.indexOf(code)
    return i === -1 ? CLASS_ORDER.length : i
  }
  return [...source].sort((a, b) => rank(a.code) - rank(b.code))
}

export function classLabeler(classes: TenderClass[]): (code: string) => string {
  const tenant = new Map(classes.map((c) => [c.code, c.label]))
  return (code) => tenant.get(code) ?? DEFAULT_CLASS_LABELS[code] ?? humanize(code)
}

// ---------------------------------------------------------------- sorting and nodes

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })
const byName = (a: TreeItem, b: TreeItem) => collator.compare(a.name, b.name) || a.id.localeCompare(b.id)
const byNumber = (a: TreeItem, b: TreeItem) =>
  collator.compare(a.document_number || a.name, b.document_number || b.name) || byName(a, b)

function makeNode(key: string, label: string, depth: number, items: TreeItem[], children: TreeNode[]): TreeNode {
  return {
    key,
    label,
    depth,
    items,
    children,
    count: items.length + children.reduce((n, c) => n + c.count, 0),
    ids: [...items.map((i) => i.id), ...children.flatMap((c) => c.ids)],
  }
}

function bucket<T>(list: T[], keyOf: (t: T) => string | null): Map<string | null, T[]> {
  const m = new Map<string | null, T[]>()
  for (const t of list) {
    const k = keyOf(t)
    const arr = m.get(k)
    if (arr) arr.push(t)
    else m.set(k, [t])
  }
  return m
}

/** Known codes in their standard order, then unknown codes alphabetically. */
function orderedKeys(present: Iterable<string>, standard: readonly string[]): string[] {
  const set = new Set(present)
  const known = standard.filter((c) => set.has(c))
  const unknown = [...set].filter((c) => !standard.includes(c)).sort()
  return [...known, ...unknown]
}

function drawingNodes(items: TreeItem[], parentKey: string): TreeNode[] {
  const byDiscipline = bucket(items, (i) => i.discipline || null)
  const disciplines = orderedKeys(
    [...byDiscipline.keys()].filter((k): k is string => k !== null),
    [...DRAWING_DISCIPLINES, ...LEGACY_DISCIPLINES],
  )
  const nodes: TreeNode[] = []
  const build = (code: string | null) => {
    const inDiscipline = byDiscipline.get(code) ?? []
    const dKey = `${parentKey}/disc:${code ?? 'none'}`
    const byType = bucket(inDiscipline, (i) => i.drawing_type || null)
    const types = orderedKeys(
      [...byType.keys()].filter((k): k is string => k !== null),
      DRAWING_TYPES,
    )
    const typeNodes = types.map((t) =>
      makeNode(`${dKey}/type:${t}`, drawingTypeLabel(t), 2, [...(byType.get(t) ?? [])].sort(byNumber), []),
    )
    if (byType.has(null)) {
      typeNodes.push(makeNode(`${dKey}/type:none`, 'Type not set', 2, [...(byType.get(null) ?? [])].sort(byNumber), []))
    }
    nodes.push(makeNode(dKey, code ? disciplineLabel(code) : 'Discipline not set', 1, [], typeNodes))
  }
  for (const d of disciplines) build(d)
  if (byDiscipline.has(null)) build(null)
  return nodes
}

/** Class -> (drawings only) discipline -> drawing type. Classless files go last under "Not classified yet". */
export function groupByType(items: TreeItem[], classLabel: (code: string) => string): TreeNode[] {
  const byClass = bucket(items, (i) => i.doc_class || null)
  const codes = orderedKeys(
    [...byClass.keys()].filter((k): k is string => k !== null),
    CLASS_ORDER,
  )
  const nodes = codes.map((code) => {
    const inClass = byClass.get(code) ?? []
    const key = `class:${code}`
    if (code === 'drawing') return makeNode(key, classLabel(code), 0, [], drawingNodes(inClass, key))
    return makeNode(key, classLabel(code), 0, [...inClass].sort(byName), [])
  })
  const none = byClass.get(null)
  if (none) nodes.push(makeNode('class:none', NOT_CLASSIFIED_LABEL, 0, [...none].sort(byName), []))
  return nodes
}

/** Folder segments of an upload-relative path (the file name is dropped). */
export function folderSegments(path: string | null): string[] {
  if (!path) return []
  return path.replace(/\\/g, '/').split('/').filter(Boolean).slice(0, -1)
}

interface FolderBuild {
  name: string
  items: TreeItem[]
  children: Map<string, FolderBuild>
}

export const NO_FOLDER_LABEL = 'Top level (no folder)'

/** The upload folder tree. Files without a folder go in one group at the end. */
export function groupByFolder(items: TreeItem[]): TreeNode[] {
  const root: FolderBuild = { name: '', items: [], children: new Map() }
  for (const item of items) {
    let cur = root
    for (const seg of folderSegments(item.path)) {
      let next = cur.children.get(seg)
      if (!next) {
        next = { name: seg, items: [], children: new Map() }
        cur.children.set(seg, next)
      }
      cur = next
    }
    cur.items.push(item)
  }
  const convert = (f: FolderBuild, parentKey: string, depth: number): TreeNode => {
    const key = `${parentKey}/${f.name}`
    const children = [...f.children.values()]
      .sort((a, b) => collator.compare(a.name, b.name))
      .map((c) => convert(c, key, depth + 1))
    return makeNode(key, f.name, depth, [...f.items].sort(byName), children)
  }
  const nodes = [...root.children.values()].sort((a, b) => collator.compare(a.name, b.name)).map((c) => convert(c, 'folder:', 0))
  if (root.items.length > 0) nodes.push(makeNode('folder:', NO_FOLDER_LABEL, 0, [...root.items].sort(byName), []))
  return nodes
}

// ---------------------------------------------------------------- filtering

export interface TreeFilters {
  q: string
  docClass: string
  status: string
  decidedBy: string
}

export const NO_FILTERS: TreeFilters = { q: '', docClass: '', status: '', decidedBy: '' }

export const isFiltering = (f: TreeFilters) => Boolean(f.q.trim() || f.docClass || f.status || f.decidedBy)

function matchesQuery(item: TreeItem, needle: string): boolean {
  return [item.name, item.path, item.document_number, item.title].some((v) => v != null && v.toLowerCase().includes(needle))
}

export function filterItems(items: TreeItem[], f: TreeFilters): TreeItem[] {
  const needle = f.q.trim().toLowerCase()
  if (!isFiltering(f)) return items
  return items.filter((i) => {
    if (needle && !matchesQuery(i, needle)) return false
    if (f.docClass) {
      if (f.docClass === NO_CLASS_FILTER ? Boolean(i.doc_class) : i.doc_class !== f.docClass) return false
    }
    if (f.status && i.display_status !== f.status) return false
    if (f.decidedBy && decidedByInfo(i)?.key !== f.decidedBy) return false
    return true
  })
}

// ---------------------------------------------------------------- expansion and paging

export const GROUP_PAGE_SIZE = 100
const SMALL_TREE = 40

/**
 * Groups start collapsed except drawings and BOQ (and the disciplines inside drawings); a small
 * tree or an active filter opens everything, since there is little to scroll through.
 */
export function defaultExpanded(node: TreeNode, mode: GroupMode, opts: { filtering: boolean; total: number }): boolean {
  if (opts.filtering || opts.total <= SMALL_TREE) return true
  if (mode === 'folder') return node.depth === 0
  if (node.key === 'class:drawing' || node.key === 'class:boq') return true
  return node.depth === 1 && node.key.startsWith('class:drawing/')
}

/** Total needs-check rows etc. are read from the summary; this is for a filtered client-side view. */
export function needsCheckItems(items: TreeItem[]): TreeItem[] {
  return items.filter((i) => i.display_status === 'needs_check').sort(byName)
}

export function drawingItemsReady(items: TreeItem[]): TreeItem[] {
  return items
    .filter((i) => i.drawing_id && i.display_status === 'ready')
    .sort((a, b) => collator.compare(a.document_number || a.name, b.document_number || b.name))
}

/** True while anything is still being unpacked or read (the tree query polls for the same condition). */
export const isIntakeBusy = (s: TreeSummary) => s.in_progress > 0 || s.packages_processing > 0
