import type { GroupCount, PackageProgress, TenderClass, TreeItem, TreeItemPage, TreeOut, TreeSummary } from './types'

// Shared builders for the tree tests.
let seq = 0

export function treeItem(over: Partial<TreeItem> = {}): TreeItem {
  seq += 1
  return {
    id: `id-${seq}`,
    package_id: 'pk1',
    name: `file-${seq}.pdf`,
    path: null,
    ext: 'pdf',
    size_bytes: 1000,
    doc_class: null,
    discipline: null,
    drawing_type: null,
    unit_type: null,
    document_number: null,
    title: null,
    revision: null,
    sheet_number: null,
    scale: null,
    confidence: null,
    status: 'routed',
    display_status: 'ready',
    status_reason: null,
    classified_by: null,
    decided_by: null,
    auto_accepted: false,
    flags: [],
    routed_kind: null,
    drawing_id: null,
    evidence_quote: null,
    evidence_page: null,
    ai_note: null,
    supersedes: [],
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

export function treeSummary(over: Partial<TreeSummary> = {}): TreeSummary {
  return {
    total: 0,
    by_display_status: {},
    by_class: {},
    needs_check: 0,
    in_progress: 0,
    pending_upload: 0,
    drawings_total: 0,
    drawings_ready: 0,
    boq_documents: [],
    first_drawing_id: null,
    addenda: 0,
    packages_processing: 0,
    auto_accept_min: 0.85,
    ai_available: true,
    ai_message: null,
    ...over,
  }
}

const CLASS_ROWS: [string, string][] = [
  ['drawing', 'Drawing'],
  ['boq', 'Bill of quantities'],
  ['specification', 'Specification'],
  ['other', 'Other'],
]

export const TEST_CLASSES: TenderClass[] = CLASS_ROWS.map(([code, label], i) => ({
  code,
  label,
  default_label: label,
  enabled: true,
  sort_order: i,
}))

export function groupCount(doc_class: string | null, count: number, discipline: string | null = null, drawing_type: string | null = null): GroupCount {
  return { doc_class, discipline, drawing_type, count }
}

export function packageProgress(over: Partial<PackageProgress> = {}): PackageProgress {
  return {
    id: 'pk1',
    label: 'Transmittal 1',
    status: 'processing',
    created_at: '2026-10-01T00:00:00Z',
    expected_count: 10,
    registered: 10,
    uploaded: 10,
    waiting: 0,
    pending_upload: 0,
    ...over,
  }
}

export function treeOut(over: Partial<TreeOut> = {}): TreeOut {
  return { summary: treeSummary(), groups: [], folders: [], packages: [], ...over }
}

export function itemPage(items: TreeItem[], total = items.length, offset = 0, limit = 100): TreeItemPage {
  return { items, total, limit, offset }
}
