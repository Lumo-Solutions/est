import type { ApprovalRequestOut } from '../types/api'

// Approval requests store a machine entity_type; every screen that lists one
// shows this label instead ("bid_settlement" told the approver nothing).
export function approvalTypeLabel(r: Pick<ApprovalRequestOut, 'entity_type' | 'settlement_version_no'>): string {
  switch (r.entity_type) {
    case 'bid_submission':
      return r.settlement_version_no != null ? `Bid settlement v${r.settlement_version_no}` : 'Bid settlement'
    case 'cost_rate_change':
      return 'Cost rate change'
    case 'vendor_onboarding':
      return 'Vendor onboarding'
    case 'prequalification':
      return 'Prequalification'
    case 'rfq_award':
      return 'RFQ award'
    case 'export':
      return 'Export'
    default:
      return r.entity_type.replace(/_/g, ' ')
  }
}

// Where the decision is made. A settlement is decided on the settlement
// cockpit (full context); anything else on the generic approval detail page.
// No list ever decides anything itself.
export function approvalHref(r: Pick<ApprovalRequestOut, 'id' | 'entity_type' | 'project_id'>): string {
  if (r.entity_type === 'bid_submission' && r.project_id) return `/projects/${r.project_id}/settlement`
  return `/approvals/${r.id}`
}

export function roleLabel(role: string | null | undefined): string {
  return role ? role.replace(/_/g, ' ') : '--'
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

// Newest first, capped: what a dashboard tile shows of a queue. The one an approver was just told about (or just
// submitted) is the one they come for; oldest-first buries it behind any backlog of stale requests.
export function newestApprovals(requests: ApprovalRequestOut[], rows = 5): ApprovalRequestOut[] {
  return [...requests].sort((a, b) => Date.parse(b.requested_at) - Date.parse(a.requested_at)).slice(0, rows)
}

