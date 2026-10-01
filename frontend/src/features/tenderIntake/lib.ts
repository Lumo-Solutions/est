import type { BadgeTone } from '../../components/Badge'
import type { TenderDocument } from './types'

export const MAX_FILE_BYTES = 250 * 1024 * 1024

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
  rules_fallback: 'Classified by rules',
  injection_suspected: 'Suspicious text ignored',
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

export function isSuperseded(doc: TenderDocument, all: TenderDocument[]): boolean {
  if (doc.routed_ref && doc.routed_ref.superseded_by) return true
  return all.some((d) => d.supersedes_id === doc.id)
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

// Mirrors backend/app/intake/constants.py (DocClass order and labels, drawing disciplines and types).
export const CLASS_ORDER = [
  'drawing',
  'boq',
  'addendum',
  'specification',
  'contract',
  'tender_instructions',
  'tender_forms',
  'clarification',
  'programme',
  'site_investigation',
  'correspondence',
  'other',
]

export const DEFAULT_CLASS_LABELS: Record<string, string> = {
  drawing: 'Drawing',
  boq: 'BOQ',
  addendum: 'Addendum',
  specification: 'Specification',
  contract: 'Contract / Conditions',
  tender_instructions: 'Tender instructions',
  tender_forms: 'Tender forms and bonds',
  clarification: 'Clarification / RFI response',
  programme: 'Programme / schedule',
  site_investigation: 'Site investigation / geotechnical',
  correspondence: 'Correspondence',
  other: 'Other',
}

// Selectable disciplines (stored in sub_type); the legacy codes are only ever displayed.
export const DRAWING_DISCIPLINES = [
  'roads_civil',
  'stormwater',
  'sewer',
  'water_supply',
  'irrigation',
  'electrical_lighting',
  'telecom',
  'landscape',
  'architectural',
  'structural',
  'mep',
]
export const LEGACY_DISCIPLINES = ['civil_infra', 'other']

export const DISCIPLINE_LABELS: Record<string, string> = {
  roads_civil: 'Roads / civil',
  stormwater: 'Stormwater drainage',
  sewer: 'Sewer',
  water_supply: 'Water supply',
  irrigation: 'Irrigation',
  electrical_lighting: 'Electrical / street lighting',
  telecom: 'Telecom',
  landscape: 'Landscape',
  architectural: 'Architectural',
  structural: 'Structural',
  mep: 'MEP',
  civil_infra: 'Civil / infrastructure',
  other: 'Other discipline',
}

export const DRAWING_TYPES = [
  'location_plan',
  'general_arrangement',
  'plan_profile',
  'cross_sections',
  'typical_details',
  'schedules',
  'setting_out',
]

export const DRAWING_TYPE_LABELS: Record<string, string> = {
  location_plan: 'Location / key plan',
  general_arrangement: 'General arrangement / layout',
  plan_profile: 'Plan & profile / longitudinal section',
  cross_sections: 'Cross sections',
  typical_details: 'Typical details',
  schedules: 'Schedules',
  setting_out: 'Setting-out',
}

export function humanize(code: string): string {
  const s = code.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export const disciplineLabel = (code: string) => DISCIPLINE_LABELS[code] ?? humanize(code)
export const drawingTypeLabel = (code: string) => DRAWING_TYPE_LABELS[code] ?? humanize(code)
