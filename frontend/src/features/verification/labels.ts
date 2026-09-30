import type { BadgeTone } from '../../components/Badge'
import type { VerificationClass, VerificationLineOut, VerificationPhase } from '../../types/api'

export const CLASS_ORDER: VerificationClass[] = [
  'match',
  'variance',
  'missing_in_drawings',
  'not_verifiable',
  'missing_in_boq',
]

export const CLASS_LABEL: Record<VerificationClass, string> = {
  match: 'Match',
  variance: 'Variance',
  missing_in_drawings: 'Missing in drawings',
  not_verifiable: 'Not verifiable',
  missing_in_boq: 'Missing in BOQ',
}

export const CLASS_TONE: Record<VerificationClass, BadgeTone> = {
  match: 'success',
  variance: 'warning',
  missing_in_drawings: 'danger',
  not_verifiable: 'neutral',
  missing_in_boq: 'info',
}

export const CLASS_HELP: Record<VerificationClass, string> = {
  match: 'Drawing quantity agrees with the BOQ',
  variance: 'Drawing quantity differs from the BOQ',
  missing_in_drawings: 'Nothing on the drawings supports this line',
  not_verifiable: 'Cannot be compared with drawing data',
  missing_in_boq: 'Drawing quantity that no BOQ line accounts for',
}

export const PHASE_LABEL: Record<VerificationPhase, string> = {
  loading: 'Loading BOQ and drawing data',
  interpreting: 'Interpreting BOQ lines',
  ranking: 'Ranking drawing evidence',
  computing: 'Computing quantities',
}

export const MAPPED_BY_LABEL: Record<VerificationLineOut['mapped_by'], string | null> = {
  ai: 'AI-mapped',
  rules: 'Rules',
  user: 'Confirmed by estimator',
  none: null,
}

export const METHOD_LABEL: Record<VerificationLineOut['method'], string | null> = {
  measured: 'Measured',
  annotated: 'Annotated',
  none: null,
}

export function fmtQty(v: number | null | undefined): string {
  return v == null ? '--' : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function fmtPct(v: number | null | undefined): string {
  return v == null ? '--' : `${v.toFixed(1)}%`
}

export function openOnDrawingPath(
  projectId: string,
  e: { ref: string; kind: string; drawing_id: string; page: number },
) {
  const base = `/projects/${projectId}/drawings/${e.drawing_id}/sheets/${e.page - 1}`
  if (e.kind === 'measurement' && e.ref.startsWith('m:')) return `${base}?measurement=${e.ref.slice(2)}`
  return base
}

export function lineDomId(id: string) {
  return `ver-line-${id}`
}
