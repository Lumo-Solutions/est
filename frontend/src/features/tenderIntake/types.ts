// Mirrors backend/app/schemas/tender_intake.py. Decimals arrive as JSON numbers.

export interface TenderPackage {
  id: string
  project_id: string
  label: string | null
  transmittal_ref: string | null
  received_date: string
  status: string
  file_count: number
  created_at: string
}

export interface TenderPackageAccepted {
  package_id: string
  file_count: number
  status: string
}

export interface EvidenceItem {
  rule?: string
  text?: string
  matched?: string
  page?: number | null
  [key: string]: unknown
}

export interface TenderClassification {
  id: string
  source: string
  doc_class: string
  sub_type: string | null
  confidence: number
  evidence: EvidenceItem[]
  metadata: Record<string, unknown>
  is_current: boolean
  created_at: string
}

export interface TenderDocument {
  id: string
  project_id: string
  package_id: string
  parent_document_id: string | null
  archive_path: string | null
  original_filename: string
  ext: string
  sha256: string
  size_bytes: number
  content_type_sniffed: string | null
  safety_status: string
  rejection_reason: string | null
  doc_class: string | null
  sub_type: string | null
  confidence: number | null
  title: string | null
  document_number: string | null
  revision_label: string | null
  metadata: Record<string, unknown>
  evidence: EvidenceItem[]
  flags: string[]
  status: string
  error_message: string | null
  duplicate_of_id: string | null
  supersedes_id: string | null
  routed_kind: string | null
  routed_ref: Record<string, unknown>
  confirmed_by: string | null
  confirmed_at: string | null
  created_at: string
}

export interface TenderDocumentDetail extends TenderDocument {
  classifications: TenderClassification[]
}

export interface TenderDocumentPage {
  items: TenderDocument[]
  total: number
  limit: number
  offset: number
}

export interface TenderDocumentFilters {
  package_id?: string
  doc_class?: string
  status?: string
  flag?: string
  q?: string
  limit?: number
  offset?: number
}

export interface RegisterFilters {
  doc_class?: string
  q?: string
  limit?: number
  offset?: number
}

export interface ConfirmItemResult {
  id: string
  ok: boolean
  status: string | null
  routed_kind: string | null
  error: string | null
}

export interface BulkConfirmResult {
  confirmed: number
  failed: number
  skipped: number
  results: ConfirmItemResult[]
}

export interface BulkConfirmBody {
  package_id?: string | null
  document_ids?: string[] | null
  min_confidence?: number | null
}

export interface AddendumLink {
  id: string
  target_document_id: string | null
  reference_text: string
  action: string
  resolved: boolean
}

export interface Addendum {
  id: string
  project_id: string
  document_id: string
  package_id: string | null
  addendum_no: string | null
  issue_date: string | null
  title: string | null
  summary: string | null
  routed_at: string
  flagged_settlement_ids: string[]
  links: AddendumLink[]
  open_settlement_ids: string[]
}

export interface BoqPrefill {
  document_id: string
  filename: string
  sheet_name: string | null
  header_row: number | null
  sheet_names: string[]
  suggested_mapping: Record<string, unknown>
}

export interface TenderClass {
  code: string
  label: string
  default_label: string
  enabled: boolean
  sort_order: number
}

export interface EditMetadataBody {
  title?: string | null
  document_number?: string | null
  revision_label?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ReclassifyBody {
  doc_class: string
  sub_type?: string | null
  drawing_type?: string | null
  note?: string | null
  confirm?: boolean
}

export interface BulkReclassifyBody extends ReclassifyBody {
  document_ids: string[]
  confirm: boolean
}

export type DisplayStatus =
  | 'queued'
  | 'reading'
  | 'classified'
  | 'extracting'
  | 'ready'
  | 'needs_check'
  | 'failed'
  | 'excluded'

// The compact document tree (GET /projects/{id}/tender-documents/tree).
export interface TreeItem {
  id: string
  package_id: string
  name: string
  path: string | null
  ext: string
  size_bytes: number
  doc_class: string | null
  discipline: string | null
  drawing_type: string | null
  unit_type: string | null
  document_number: string | null
  title: string | null
  revision: string | null
  sheet_number: string | null
  scale: string | null
  confidence: number | null
  status: string
  display_status: DisplayStatus | string
  status_reason: string | null
  classified_by: 'ai' | 'rules' | 'user' | null
  decided_by: 'ai' | 'rules' | 'user' | null
  auto_accepted: boolean
  flags: string[]
  routed_kind: 'drawing' | 'boq_wizard' | 'addendum' | 'register' | 'duplicate' | 'not_measurable' | null
  drawing_id: string | null
  evidence_quote: string | null
  evidence_page: number | null
  ai_note: string | null
  supersedes: string[]
  created_at: string
}

export interface TreeSummary {
  total: number
  by_display_status: Record<string, number>
  by_class: Record<string, number>
  needs_check: number
  in_progress: number
  drawings_total: number
  drawings_ready: number
  boq_documents: string[]
  addenda: number
  packages_processing: number
  auto_accept_min: number
  ai_available: boolean
  ai_message: string | null
}

export interface TreeOut {
  items: TreeItem[]
  summary: TreeSummary
}
