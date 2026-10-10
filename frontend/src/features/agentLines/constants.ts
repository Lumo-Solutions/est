import type { BadgeTone } from '../../components/Badge'
import { Role } from '../../lib/roles'

// Mirrors the contract: lead_estimator, procurement_head, bd_director and managing_director confirm;
// an estimator only reads.
export const AGENT_ACTION_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

export const FLAG_INFO: Record<string, { label: string; meaning: string; tone: BadgeTone }> = {
  agent_estimate: {
    label: 'Estimate',
    meaning: "The agent's own estimate, not a quote or a library rate. Check the evidence before you confirm.",
    tone: 'warning',
  },
  no_document_check: {
    label: 'No document check',
    meaning: 'The agent did not check this rate against the tender documents.',
    tone: 'warning',
  },
  stale_rate: { label: 'Stale rate', meaning: 'The rate is older than the freshness limit.', tone: 'warning' },
  quote_exclusions: {
    label: 'Quote exclusions',
    meaning: 'The quote lists exclusions that may leave part of this line uncovered.',
    tone: 'warning',
  },
  vendor_not_eligible: {
    label: 'Vendor not eligible',
    meaning: 'The vendor is not approved for this trade or region.',
    tone: 'danger',
  },
  large_deviation: {
    label: 'Large deviation',
    meaning: 'The rate is far from the history or library median for this item.',
    tone: 'danger',
  },
  needs_fx: {
    label: 'Needs FX',
    meaning: 'The rate is in another currency and needs an FX rate before it is comparable.',
    tone: 'warning',
  },
  quantity_variance: {
    label: 'Quantity variance',
    meaning: 'The measured quantity differs from the BOQ quantity. The BOQ quantity is not changed.',
    tone: 'warning',
  },
  unit_alias: {
    label: 'Unit alias',
    meaning: 'The unit was matched by alias (for example m2 and sqm). Check it is the same unit.',
    tone: 'info',
  },
}

export function flagInfo(flag: string): { label: string; meaning: string; tone: BadgeTone } {
  const known = FLAG_INFO[flag]
  if (known) return known
  const label = flag.replace(/_/g, ' ')
  return { label: label.charAt(0).toUpperCase() + label.slice(1), meaning: 'Flagged by the agent.', tone: 'neutral' }
}

export const confidenceTone = (c: number): BadgeTone => (c >= 0.85 ? 'success' : c >= 0.6 ? 'warning' : 'danger')
export const formatConfidence = (c: number) => `${Math.round(c * 100)}%`

export const lineDomId = (lineId: string) => `agent-line-${lineId}`
