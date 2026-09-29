import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge, type BadgeTone } from '../components/Badge'
import { PageTitle } from '../components/PageTitle'
import { SkeletonRows } from '../components/Skeleton'
import { Spinner } from '../components/Spinner'
import { Table, TableCard, Td, Th } from '../components/Table'
import { TextPromptModal } from '../components/TextPromptModal'
import { useApproval, useDecideApproval, useSubmitterName } from '../features/approvals/api'
import { ApiError } from '../lib/api'
import { approvalHref, approvalTypeLabel, formatWhen, roleLabel } from '../lib/approvals'
import { formatMarginPct, formatMoney } from '../lib/format'

const STATUS_TONE: Record<string, BadgeTone> = {
  approved: 'success',
  rejected: 'danger',
  pending: 'warning',
  skipped: 'neutral',
}

const LINK_CLASS =
  'rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

// The decision page for approvals that have no richer home (today:
// cost_rate_change). A bid settlement is decided on the settlement cockpit,
// which also syncs the settlement's own status, so it is read-only here and
// links there. Server-side rules (SoD, role, step-up) are unchanged: this
// page only mirrors them to decide which controls to show.
export function ApprovalDetailPage() {
  const { requestId } = useParams()
  const { data: r, isLoading, isError, error } = useApproval(requestId)
  const decide = useDecideApproval(requestId)
  const submitterName = useSubmitterName()
  const [rejectOpen, setRejectOpen] = useState(false)
  const stepUpPending = decide.isError && decide.error instanceof ApiError && decide.error.isStepUpRequired

  if (isLoading) {
    return (
      <div className="px-6 py-6 xl:px-10">
        <PageTitle>Approval</PageTitle>
        <div className="mt-4">
          <SkeletonRows count={3} />
        </div>
      </div>
    )
  }
  if (isError || !r) {
    return (
      <div className="px-6 py-6 xl:px-10">
        <PageTitle>Approval</PageTitle>
        <p role="alert" className="mt-4 text-sm text-danger">
          {error?.message ?? 'Approval not found.'}
        </p>
      </div>
    )
  }

  const isSettlement = r.entity_type === 'bid_submission'
  const snapshot = r.payload_snapshot ? Object.entries(r.payload_snapshot) : []

  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>{approvalTypeLabel(r)}</PageTitle>
      <p className="mt-1 text-sm text-muted">
        <Link to="/approvals" className={LINK_CLASS}>
          Back to approvals
        </Link>
      </p>

      <div className="mt-4 rounded-card bg-white p-5">
        <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-2">Project</dt>
            <dd>{r.project_code ? `${r.project_code} -- ${r.project_name}` : '--'}</dd>
          </div>
          <div>
            <dt className="text-ink-2">Status</dt>
            <dd>
              <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status}</Badge>
            </dd>
          </div>
          <div>
            <dt className="text-ink-2">Amount</dt>
            <dd className="tabular-nums">
              {formatMoney(r.amount, r.currency)}
              {r.margin_on_sell_pct != null && <> -- margin on sell {formatMarginPct(r.margin_on_sell_pct)}%</>}
            </dd>
          </div>
          <div>
            <dt className="text-ink-2">Submitted</dt>
            <dd>
              {submitterName(r)} on {formatWhen(r.requested_at)}
            </dd>
          </div>
          <div>
            <dt className="text-ink-2">Waiting on</dt>
            <dd>{roleLabel(r.waiting_role)}</dd>
          </div>
          <div>
            <dt className="text-ink-2">Subject</dt>
            <dd className="break-all text-xs text-ink-2">
              {r.entity_type} {r.entity_id}
            </dd>
          </div>
        </dl>

        {snapshot.length > 0 && (
          <div className="mt-4">
            <h2 className="text-sm font-semibold text-ink-title">Details at submission</h2>
            <dl className="mt-1 grid grid-cols-1 gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
              {snapshot.map(([k, v]) => (
                <div key={k}>
                  <dt className="inline text-ink-2">{k.replace(/_/g, ' ')}: </dt>
                  <dd className="inline">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <h2 className="mt-6 text-lg font-semibold text-ink-title">Approval steps</h2>
      <TableCard className="mt-2">
        <Table aria-label="Approval steps">
          <thead>
            <tr>
              <Th>Step</Th>
              <Th>Role</Th>
              <Th>Status</Th>
              <Th>Decided</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {r.steps.map((s) => (
              <tr key={s.id} className="border-b border-row-rule">
                <Td>{s.seq}</Td>
                <Td>{roleLabel(s.required_role)}</Td>
                <Td>
                  <Badge tone={STATUS_TONE[s.status] ?? 'neutral'}>{s.status}</Badge>
                </Td>
                <Td>{s.decided_at ? formatWhen(s.decided_at) : '--'}</Td>
                <Td>{s.decision_note ?? '--'}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </TableCard>

      <div className="mt-6">
        {isSettlement ? (
          <Link to={approvalHref(r)} className={LINK_CLASS}>
            Open the settlement to decide
          </Link>
        ) : r.view_state === 'actionable' ? (
          <div className="flex flex-col items-start gap-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={decide.isPending}
                onClick={() => decide.mutate({ approve: true })}
                className="inline-flex items-center gap-1.5 rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {decide.isPending && <Spinner className="text-white" />}
                Approve
              </button>
              <button
                type="button"
                disabled={decide.isPending}
                onClick={() => setRejectOpen(true)}
                className="rounded-pill border border-red-700 px-4 py-1.5 text-sm text-red-700 transition-colors duration-150 hover:bg-danger-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Reject
              </button>
            </div>
            {stepUpPending ? (
              <p role="status" className="inline-flex items-center gap-1.5 text-xs text-muted">
                <Spinner className="text-muted" />
                Verifying... redirecting you to confirm your identity before this decision can complete.
              </p>
            ) : (
              decide.isError && (
                <p role="alert" className="text-xs text-danger">
                  {decide.error.message}
                </p>
              )
            )}
            <TextPromptModal
              open={rejectOpen}
              title="Reject request"
              message="Rejection reason?"
              submitLabel="Reject"
              onCancel={() => setRejectOpen(false)}
              onSubmit={(note) => {
                decide.mutate({ approve: false, note })
                setRejectOpen(false)
              }}
            />
          </div>
        ) : r.view_state === 'awaiting_other' ? (
          <p className="text-sm text-muted">Awaiting a different approver</p>
        ) : r.status === 'pending' ? (
          <p className="text-sm text-muted">Waiting on {roleLabel(r.waiting_role)}; it is not your decision.</p>
        ) : null}
      </div>
    </div>
  )
}
