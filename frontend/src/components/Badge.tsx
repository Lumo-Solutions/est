// docs/ui-design-system.md section 4.8 -- one shared badge, four semantic
// tones (+ neutral), replacing the ~6 near-duplicate STATUS_STYLES maps
// built independently page by page across Phases 0-3. The status->tone
// MAPPING stays per-page (a TypologyClusterStatus and a DrawingStatus
// don't share a vocabulary), only the component and its tone tokens are
// shared.
export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: 'bg-success-subtle text-emerald-700',
  warning: 'bg-warning-subtle text-amber-800',
  danger: 'bg-danger-subtle text-red-700',
  info: 'bg-info-subtle text-sky-700',
  neutral: 'bg-slate-100 text-slate-600',
}

export function Badge({ tone, children }: { tone: BadgeTone; children: React.ReactNode }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}>{children}</span>
}
