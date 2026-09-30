import type { BadgeTone } from '../../components/Badge'
import { Role } from '../../lib/roles'

// Mirrors the backend: running an AI pass and bulk-accept are lead_estimator
// and above (estimators can still work existing proposals).
export const AI_RUN_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

// Flags are always shown as labelled badges (never colour alone). Blocking
// flags use the warning/danger tones; informational ones stay neutral/info.
export const FLAG_INFO: Record<string, { label: string; tone: BadgeTone }> = {
  unit_mismatch: { label: 'Unit differs', tone: 'danger' },
  stale_rate: { label: 'Stale rate', tone: 'warning' },
  quote_exclusions: { label: 'Quote has exclusions', tone: 'warning' },
  vendor_not_eligible: { label: 'Vendor not eligible', tone: 'danger' },
  large_deviation: { label: 'Far from history', tone: 'warning' },
  needs_fx: { label: 'Needs FX rate', tone: 'warning' },
  single_source: { label: 'Single source', tone: 'info' },
  deviation_from_history: { label: 'Differs from history', tone: 'info' },
  unit_alias: { label: 'Unit alias', tone: 'info' },
}

export function flagInfo(flag: string): { label: string; tone: BadgeTone } {
  return FLAG_INFO[flag] ?? { label: flag.replace(/_/g, ' '), tone: 'neutral' }
}
