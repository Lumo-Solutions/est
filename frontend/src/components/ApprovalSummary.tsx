import { Link } from 'react-router-dom'
import { useSubmitterName } from '../features/approvals/api'
import { approvalHref, approvalTypeLabel, formatWhen, roleLabel } from '../lib/approvals'
import { formatMarginPct, formatMoney } from '../lib/format'
import type { ApprovalRequestOut } from '../types/api'

// One approval, as much as an approver needs to decide whether to open it:
// project, readable type, amount (+ margin on sell for settlements), who
// submitted it and when, and the role it's waiting on. The whole block is a
// link to the page where the decision is made -- never an inline approve.
export function ApprovalSummary({ request: r }: { request: ApprovalRequestOut }) {
  const submitterName = useSubmitterName()
  return (
    <Link
      to={approvalHref(r)}
      className="block rounded px-1 py-1 text-ink hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      <span className="block font-medium">
        {r.project_code ? `${r.project_code} -- ${r.project_name}` : 'No project'}
      </span>
      <span className="block">
        {approvalTypeLabel(r)} -- {formatMoney(r.amount, r.currency)}
        {r.margin_on_sell_pct != null && (
          <span className="text-ink-2"> -- margin on sell {formatMarginPct(r.margin_on_sell_pct)}%</span>
        )}
      </span>
      <span className="block text-xs text-ink-2">
        Submitted by {submitterName(r)} on {formatWhen(r.requested_at)}
        {r.waiting_role && <> -- waiting on {roleLabel(r.waiting_role)}</>}
      </span>
    </Link>
  )
}
