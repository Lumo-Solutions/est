import type { BadgeTone } from '../../components/Badge'
import type { TenderDocument } from './types'

export const MAX_FILE_BYTES = 60 * 1024 * 1024
export const MAX_BATCH_FILES = 20
export const MAX_BATCH_BYTES = 200 * 1024 * 1024

export const UPLOAD_ROLES = ['estimator', 'lead_estimator', 'procurement_head', 'bd_director', 'managing_director']
export const CONFIRM_ROLES = ['lead_estimator', 'procurement_head', 'bd_director', 'managing_director']

export function confidenceTone(c: number): BadgeTone {
  if (c >= 0.85) return 'success'
  if (c >= 0.5) return 'warning'
  return 'danger'
}

export function formatConfidence(c: number | null | undefined): string {
  return c == null ? '--' : `${Math.round(c * 100)}%`
}

export const FLAG_LABELS: Record<string, string> = {
  duplicate: 'Duplicate',
  revision_of: 'Revision',
  conflict: 'Conflict',
  low_confidence: 'Low confidence',
  not_measurable: 'Not measurable',
  convert_to_dxf: 'Convert to DXF',
  model_unavailable: 'Model unavailable',
}

export const FILTERABLE_FLAGS = [
  'duplicate',
  'conflict',
  'low_confidence',
  'not_measurable',
  'convert_to_dxf',
  'revision_of',
  'model_unavailable',
]

export function flagLabel(flag: string): string {
  return FLAG_LABELS[flag] ?? flag.replace(/_/g, ' ')
}

export const DOC_STATUSES = ['received', 'processing', 'proposed', 'confirmed', 'routed', 'failed', 'rejected', 'excluded', 'archive']

const STATUS_TONE: Record<string, BadgeTone> = {
  proposed: 'warning',
  confirmed: 'info',
  routed: 'success',
  failed: 'danger',
  rejected: 'danger',
  excluded: 'neutral',
  archive: 'neutral',
}

export function statusTone(status: string): BadgeTone {
  return STATUS_TONE[status] ?? 'neutral'
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** Split files into upload batches of at most maxFiles files and maxBytes total. */
export function splitIntoBatches<T extends { size: number }>(
  files: T[],
  maxFiles = MAX_BATCH_FILES,
  maxBytes = MAX_BATCH_BYTES,
): T[][] {
  const batches: T[][] = []
  let current: T[] = []
  let bytes = 0
  for (const f of files) {
    if (current.length > 0 && (current.length >= maxFiles || bytes + f.size > maxBytes)) {
      batches.push(current)
      current = []
      bytes = 0
    }
    current.push(f)
    bytes += f.size
  }
  if (current.length > 0) batches.push(current)
  return batches
}

export function isSuperseded(doc: TenderDocument, all: TenderDocument[]): boolean {
  if (doc.routed_ref && doc.routed_ref.superseded_by) return true
  return all.some((d) => d.supersedes_id === doc.id)
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}
