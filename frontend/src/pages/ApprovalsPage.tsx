import { Link } from 'react-router-dom'
import { Badge, type BadgeTone } from '../components/Badge'
import { PageTitle } from '../components/PageTitle'
import { SkeletonRows } from '../components/Skeleton'
import { Table, TableCard, Td, Th } from '../components/Table'
import { useApprovalsInbox, useSubmitterName } from '../features/approvals/api'
import { approvalHref, approvalTypeLabel, formatWhen, roleLabel } from '../lib/approvals'
import { formatMarginPct, formatMoney } from '../lib/format'
import type { ApprovalRequestOut } from '../types/api'

const STATUS_TONE: Record<string, BadgeTone> = {
  approved: 'success',
  rejected: 'danger',
  pending: 'warning',
}

function ProjectCell({ r }: { r: ApprovalRequestOut }) {
  return r.project_code ? (
    <>
      <span className="font-medium">{r.project_code}</span>
      <span className="block text-xs text-ink-2">{r.project_name}</span>
    </>
  ) : (
    <span className="text-ink-2">--</span>
  )
}

function AmountCell({ r }: { r: ApprovalRequestOut }) {
  return (
    <>
      {formatMoney(r.amount, r.currency)}
      {r.margin_on_sell_pct != null && (
        <span className="block text-xs text-ink-2">margin on sell {formatMarginPct(r.margin_on_sell_pct)}%</span>
      )}
    </>
  )
}

const LINK_CLASS =
  'rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

export function ApprovalsPage() {
  const { data, isLoading, isError, error } = useApprovalsInbox()
  const submitterName = useSubmitterName()

  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Approvals</PageTitle>
      <p className="mt-1 text-sm text-muted">
        Open an item to see its full context and decide it there. Nothing is approved from this list.
      </p>

      {isLoading && (
        <div className="mt-4">
          <SkeletonRows count={3} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error?.message ?? 'Failed to load approvals.'}
        </p>
      )}

      {data && (
        <>
          <h2 className="mt-6 text-lg font-semibold text-ink-title">Pending for me ({data.pending.length})</h2>
          {data.pending.length === 0 ? (
            <p className="mt-2 text-sm text-muted">Nothing waiting on your decision.</p>
          ) : (
            <TableCard className="mt-2">
              <Table aria-label="Pending approvals">
                <thead>
                  <tr>
                    <Th>Project</Th>
                    <Th>Type</Th>
                    <Th numeric>Amount</Th>
                    <Th>Submitted</Th>
                    <Th>Waiting on</Th>
                    <Th>Action</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.pending.map((r) => (
                    <tr key={r.id} className="border-b border-row-rule hover:bg-canvas">
                      <Td>
                        <ProjectCell r={r} />
                      </Td>
                      <Td>{approvalTypeLabel(r)}</Td>
                      <Td numeric className="tabular-nums">
                        <AmountCell r={r} />
                      </Td>
                      <Td>
                        {submitterName(r)}
                        <span className="block text-xs text-ink-2">{formatWhen(r.requested_at)}</span>
                      </Td>
                      <Td>{roleLabel(r.waiting_role)}</Td>
                      <Td>
                        {r.view_state === 'awaiting_other' ? (
                          <span className="text-xs text-muted">Awaiting a different approver</span>
                        ) : (
                          <Link to={approvalHref(r)} className={LINK_CLASS}>
                            Review
                            <span className="sr-only">
                              {' '}
                              {approvalTypeLabel(r)} for {r.project_code ?? 'no project'}
                            </span>
                          </Link>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableCard>
          )}

          <h2 className="mt-8 text-lg font-semibold text-ink-title">
            Decided by me, last 30 days ({data.recent.length})
          </h2>
          {data.recent.length === 0 ? (
            <p className="mt-2 text-sm text-muted">You have not decided anything recently.</p>
          ) : (
            <TableCard className="mt-2">
              <Table aria-label="Recently decided approvals">
                <thead>
                  <tr>
                    <Th>Project</Th>
                    <Th>Type</Th>
                    <Th numeric>Amount</Th>
                    <Th>Status</Th>
                    <Th>Details</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((r) => (
                    <tr key={r.id} className="border-b border-row-rule hover:bg-canvas">
                      <Td>
                        <ProjectCell r={r} />
                      </Td>
                      <Td>{approvalTypeLabel(r)}</Td>
                      <Td numeric className="tabular-nums">
                        <AmountCell r={r} />
                      </Td>
                      <Td>
                        <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status}</Badge>
                      </Td>
                      <Td>
                        <Link to={approvalHref(r)} className={LINK_CLASS}>
                          View
                          <span className="sr-only">
                            {' '}
                            {approvalTypeLabel(r)} for {r.project_code ?? 'no project'}
                          </span>
                        </Link>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableCard>
          )}
        </>
      )}
    </div>
  )
}
