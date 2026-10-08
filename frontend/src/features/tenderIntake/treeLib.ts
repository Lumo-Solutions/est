import type { BadgeTone } from '../../components/Badge'
import {
  CLASS_ORDER,
  DEFAULT_CLASS_LABELS,
  DRAWING_DISCIPLINES,
  DRAWING_TYPES,
  LEGACY_DISCIPLINES,
  disciplineLabel,
  drawingTypeLabel,
  flagLabel,
  humanize,
} from './lib'
import type { DocFilter, FolderCount, GroupCount, TenderClass, TreeItem, TreeSummary } from './types'

// Pure logic for the project document tree. The server owns the file lists and the counts; this builds the group
// nodes from the counts and maps a node (or the search filters) to the DocFilter that lists its files.

export type GroupMode = 'type' | 'folder'

export interface TreeNode {
  key: string
  label: string
  depth: number
  /** Files in this group and everything below it. */
  count: number
  /** Files directly in this group (leaf groups, or a folder's own files). */
  directCount: number
  children: TreeNode[]
  /** Lists this node's own files; null when it has none directly (it only holds sub-groups). */
  listFilter: DocFilter | null
  /** Selects everything in this group and below (the group checkbox). */
  selectFilter: DocFilter
  /**
   * The class the files may have: a class code, 'none' (no class), or 'mixed' (a folder: any class). Decides whether
   * changing the class could take drawings out of the takeoff.
   */
  classHint: string
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
  too_large: 'warning',
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

/** The label of a flag badge ("Too large" is newer than the shared flagLabel). */
export function flagText(flag: string): string {
  return flag === 'too_large' ? 'Too large' : flagLabel(flag)
}

/**
 * "Confirm all" in Needs your check: every file that has a proposed class, except those whose class needs a person's
 * eyes (a conflict or suspicious text). Server-side, so it covers every matching file, not the rows on screen.
 */
export const CONFIRM_ALL_FILTER: DocFilter = {
  display_status: 'needs_check',
  has_class: true,
  exclude_flags: ['conflict', 'injection_suspected'],
}
export const NEEDS_CHECK_FILTER: DocFilter = { display_status: 'needs_check' }

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

// ---------------------------------------------------------------- nodes from counts

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

/** Known codes in their standard order, then unknown codes alphabetically. */
function orderedKeys(present: Iterable<string>, standard: readonly string[]): string[] {
  const set = new Set(present)
  const known = standard.filter((c) => set.has(c))
  const unknown = [...set].filter((c) => !standard.includes(c)).sort()
  return [...known, ...unknown]
}

const sumCounts = (rows: GroupCount[]) => rows.reduce((n, r) => n + r.count, 0)

function groupBy(rows: GroupCount[], keyOf: (r: GroupCount) => string | null): Map<string | null, GroupCount[]> {
  const m = new Map<string | null, GroupCount[]>()
  for (const r of rows) {
    const k = keyOf(r)
    const arr = m.get(k)
    if (arr) arr.push(r)
    else m.set(k, [r])
  }
  return m
}

function drawingNodes(rows: GroupCount[], parentKey: string): TreeNode[] {
  const byDiscipline = groupBy(rows, (r) => r.discipline || null)
  const disciplines = orderedKeys(
    [...byDiscipline.keys()].filter((k): k is string => k !== null),
    [...DRAWING_DISCIPLINES, ...LEGACY_DISCIPLINES],
  )
  const nodes: TreeNode[] = []
  const build = (code: string | null) => {
    const inDiscipline = byDiscipline.get(code) ?? []
    const dKey = `${parentKey}/disc:${code ?? 'none'}`
    const dFilter: DocFilter = { doc_class: 'drawing', discipline: code ?? NO_CLASS_FILTER }
    const byType = groupBy(inDiscipline, (r) => r.drawing_type || null)
    const typeNode = (t: string | null): TreeNode => {
      const count = sumCounts(byType.get(t) ?? [])
      const filter: DocFilter = { ...dFilter, drawing_type: t ?? NO_CLASS_FILTER }
      return {
        key: `${dKey}/type:${t ?? 'none'}`,
        label: t ? drawingTypeLabel(t) : 'Type not set',
        depth: 2,
        count,
        directCount: count,
        children: [],
        listFilter: filter,
        selectFilter: filter,
        classHint: 'drawing',
      }
    }
    const types = orderedKeys(
      [...byType.keys()].filter((k): k is string => k !== null),
      DRAWING_TYPES,
    )
    const children = types.map(typeNode)
    if (byType.has(null)) children.push(typeNode(null))
    nodes.push({
      key: dKey,
      label: code ? disciplineLabel(code) : 'Discipline not set',
      depth: 1,
      count: sumCounts(inDiscipline),
      directCount: 0,
      children,
      listFilter: null,
      selectFilter: dFilter,
      classHint: 'drawing',
    })
  }
  for (const d of disciplines) build(d)
  if (byDiscipline.has(null)) build(null)
  return nodes
}

/**
 * "By document type" from the server's group counts: class -> (drawings only) discipline -> drawing type, counts
 * rolled up. Files with no class go last under "Not classified yet". Zero-count rows are dropped.
 */
export function buildTypeNodes(groups: GroupCount[], classLabel: (code: string) => string): TreeNode[] {
  const rows = groups.filter((g) => g.count > 0)
  const byClass = groupBy(rows, (r) => r.doc_class || null)
  const codes = orderedKeys(
    [...byClass.keys()].filter((k): k is string => k !== null),
    CLASS_ORDER,
  )
  const nodes: TreeNode[] = codes.map((code) => {
    const inClass = byClass.get(code) ?? []
    const key = `class:${code}`
    const filter: DocFilter = { doc_class: code }
    const count = sumCounts(inClass)
    const label = classLabel(code)
    if (code === 'drawing') {
      return { key, label, depth: 0, count, directCount: 0, children: drawingNodes(inClass, key), listFilter: null, selectFilter: filter, classHint: code }
    }
    return { key, label, depth: 0, count, directCount: count, children: [], listFilter: filter, selectFilter: filter, classHint: code }
  })
  const none = byClass.get(null)
  if (none) {
    const filter: DocFilter = { doc_class: NO_CLASS_FILTER }
    const count = sumCounts(none)
    nodes.push({ key: 'class:none', label: NOT_CLASSIFIED_LABEL, depth: 0, count, directCount: count, children: [], listFilter: filter, selectFilter: filter, classHint: 'none' })
  }
  return nodes
}

export const NO_FOLDER_LABEL = 'Top level (no folder)'

interface FolderBuild {
  name: string
  path: string
  direct: number
  children: Map<string, FolderBuild>
}

/**
 * "Original folders" from the folder -> direct file count map: the folder tree with counts rolled up. A folder's own
 * files are listed with `folder` (exact); its checkbox selects the subtree with `include_subfolders`. Files with no
 * folder go in one group at the end.
 */
export function buildFolderNodes(folders: FolderCount[]): TreeNode[] {
  const root: FolderBuild = { name: '', path: '', direct: 0, children: new Map() }
  for (const f of folders) {
    if (f.count <= 0) continue
    const segs = f.folder.replace(/\\/g, '/').split('/').filter(Boolean)
    let cur = root
    for (const seg of segs) {
      let next = cur.children.get(seg)
      if (!next) {
        next = { name: seg, path: cur.path ? `${cur.path}/${seg}` : seg, direct: 0, children: new Map() }
        cur.children.set(seg, next)
      }
      cur = next
    }
    cur.direct += f.count
  }
  const convert = (f: FolderBuild, depth: number): TreeNode => {
    const children = [...f.children.values()].sort((a, b) => collator.compare(a.name, b.name)).map((c) => convert(c, depth + 1))
    return {
      key: `folder:${f.path}`,
      label: f.name,
      depth,
      count: f.direct + children.reduce((n, c) => n + c.count, 0),
      directCount: f.direct,
      children,
      listFilter: f.direct > 0 ? { folder: f.path } : null,
      selectFilter: { folder: f.path, include_subfolders: true },
      classHint: 'mixed',
    }
  }
  const nodes = [...root.children.values()].sort((a, b) => collator.compare(a.name, b.name)).map((c) => convert(c, 0))
  if (root.direct > 0) {
    nodes.push({
      key: 'folder:',
      label: NO_FOLDER_LABEL,
      depth: 0,
      count: root.direct,
      directCount: root.direct,
      children: [],
      listFilter: { folder: '' },
      selectFilter: { folder: '' },
      classHint: 'mixed',
    })
  }
  return nodes
}

/** Folder segments of an upload-relative path (the file name is dropped). */
export function folderSegments(path: string | null): string[] {
  if (!path) return []
  return path.replace(/\\/g, '/').split('/').filter(Boolean).slice(0, -1)
}

// ---------------------------------------------------------------- filtering (server-side)

export interface TreeFilters {
  q: string
  docClass: string
  status: string
  decidedBy: string
}

export const NO_FILTERS: TreeFilters = { q: '', docClass: '', status: '', decidedBy: '' }

export const isFiltering = (f: TreeFilters) => Boolean(f.q.trim() || f.docClass || f.status || f.decidedBy)

/** The /items filter for the search box and the Class / Status / Decided-by selects. */
export function toDocFilter(f: TreeFilters): DocFilter {
  const out: DocFilter = {}
  if (f.q.trim()) out.q = f.q.trim()
  if (f.docClass) out.doc_class = f.docClass
  if (f.status) out.display_status = f.status
  if (f.decidedBy) out.decided_by = f.decidedBy
  return out
}

// ---------------------------------------------------------------- expansion

const SMALL_TREE = 40

/**
 * Groups start collapsed except drawings and BOQ (and the disciplines inside drawings); a small tree opens
 * everything, since there is little to scroll through.
 */
export function defaultExpanded(node: TreeNode, mode: GroupMode, opts: { total: number }): boolean {
  if (opts.total <= SMALL_TREE) return true
  if (mode === 'folder') return node.depth === 0
  if (node.key === 'class:drawing' || node.key === 'class:boq') return true
  return node.depth === 1 && node.key.startsWith('class:drawing/')
}

/** True while anything is still being uploaded, unpacked or read (the tree query polls for the same condition). */
export const isIntakeBusy = (s: TreeSummary) => s.in_progress > 0 || s.pending_upload > 0 || s.packages_processing > 0

/** At most `max` messages, plus how many more there were (for "and K more"). */
export function capList<T>(list: T[], max = 20): { shown: T[]; more: number } {
  return { shown: list.slice(0, max), more: Math.max(0, list.length - max) }
}
