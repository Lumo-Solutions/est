import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApprovalSummary } from '../components/ApprovalSummary'
import { SkeletonRows } from '../components/Skeleton'
import {
  useExpiringCertificatesForDashboard,
  useOpenVendorDuplicatesForDashboard,
  usePendingApprovalsForMe,
  useQuarantineQueueForDashboard,
} from '../features/dashboard/api'
import { Role } from '../lib/roles'
import type { ApprovalRequestOut } from '../types/api'
import { PageTitle } from '../components/PageTitle'

// Phase 3 gap-fill (docs/ui-qa-brief.md): "Add a home dashboard per role
// that answers 'what needs my attention?'." Deliberately scoped to tiles
// backed by a REAL, already-queryable (or newly added this chunk, see
// docs/ui-qa/log.md) list endpoint -- per the brief's own "add backend
// endpoints only where a screen genuinely needs one," this does NOT invent
// a cross-project BOQ/RFQ/settlement-status aggregate that no endpoint
// produces today (every settlement/BOQ list is project-scoped; there is
// no "every project's settlements in draft" endpoint to build that tile
// from honestly). estimator's section says so explicitly rather than
// showing a fake or misleading number.
//
// New route (`/dashboard`), NOT a replacement for `/` -- ProjectsListPage
// stays the default landing page (unclear whether making the dashboard the
// forced post-login redirect is wanted without a real user testing it, and
// a nav link is a safe, reversible way to make it reachable either way).

const APPROVAL_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
const VENDOR_MANAGEMENT_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
const QUARANTINE_ROLES = [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

function Tile({
  title,
  isLoading,
  isError,
  errorMessage,
  count,
  emptyLabel,
  children,
}: {
  title: string
  isLoading: boolean
  isError: boolean
  errorMessage?: string
  count: number
  emptyLabel: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-card bg-white p-5">
      <h2 className="text-lg font-semibold text-ink-title">
        {/* text-slate-400 measured 2.63:1 via axe on the sidebar's own
            section label in an earlier Phase 4 chunk (AppShell) -- same
            failure mode here, same fix. */}
        {title} {!isLoading && !isError && <span className="text-ink-2">({count})</span>}
      </h2>
      {isLoading && (
        <div className="mt-2">
          <SkeletonRows count={2} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {errorMessage ?? 'Failed to load.'}
        </p>
      )}
      {!isLoading && !isError && count === 0 && <p className="mt-2 text-sm text-muted">{emptyLabel}</p>}
      {!isLoading && !isError && count > 0 && <ul className="mt-2 space-y-1 text-sm">{children}</ul>}
    </div>
  )
}

const APPROVAL_TILE_ROWS = 5

// The tile lists the NEWEST requests first, not the oldest: the one an approver was just told about (or just
// submitted) is the one they come here for, and oldest-first buries it behind any backlog of stale requests. Nothing is
// hidden silently: the heading carries the total, and when rows are left out the tile says how many and links to
// /approvals, which lists the whole queue (oldest first, so the longest-waiting one is not lost either).
export function newestApprovals(requests: ApprovalRequestOut[], rows = APPROVAL_TILE_ROWS): ApprovalRequestOut[] {
  return [...requests].sort((a, b) => Date.parse(b.requested_at) - Date.parse(a.requested_at)).slice(0, rows)
}

export function ApprovalsTile() {
  const { data, isLoading, isError, error } = usePendingApprovalsForMe()
  const total = data?.length ?? 0
  return (
    <Tile
      title="Approvals waiting for me"
      isLoading={isLoading}
      isError={isError}
      errorMessage={error?.message}
      count={total}
      emptyLabel="Nothing waiting on your decision."
    >
      {data && newestApprovals(data).map((r) => (
        <li key={r.id}>
          <ApprovalSummary request={r} />
        </li>
      ))}
      {total > 0 && (
        <li className="pt-1">
          {total > APPROVAL_TILE_ROWS && (
            <span className="mb-1 block text-xs text-ink-2">
              Showing the {APPROVAL_TILE_ROWS} newest of {total}.
            </span>
          )}
          <Link
            to="/approvals"
            className="rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            View all {total}
          </Link>
        </li>
      )}
    </Tile>
  )
}

function QuarantineTile() {
  const { data, isLoading, isError, error } = useQuarantineQueueForDashboard()
  return (
    <Tile
      title="Quarantined mail needing review"
      isLoading={isLoading}
      isError={isError}
      errorMessage={error?.message}
      count={data?.length ?? 0}
      emptyLabel="Queue is clear."
    >
      {data?.slice(0, 5).map((e) => (
        <li key={e.id}>
          <Link
            to="/projects"
            className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {e.subject ?? e.from_address}
          </Link>
        </li>
      ))}
    </Tile>
  )
}

function VendorDuplicatesTile() {
  const { data, isLoading, isError, error } = useOpenVendorDuplicatesForDashboard()
  return (
    <Tile
      title="Vendor duplicates open"
      isLoading={isLoading}
      isError={isError}
      errorMessage={error?.message}
      count={data?.length ?? 0}
      emptyLabel="No open duplicate candidates."
    >
      {data?.slice(0, 5).map((d) => (
        <li key={d.id}>
          <Link
            to="/vendors/duplicates"
            className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Candidate pair (score {d.score.toFixed(2)})
          </Link>
        </li>
      ))}
    </Tile>
  )
}

function ExpiringCertificatesTile() {
  const { data, isLoading, isError, error } = useExpiringCertificatesForDashboard(30)
  return (
    <Tile
      title="Certificates expiring within 30 days"
      isLoading={isLoading}
      isError={isError}
      errorMessage={error?.message}
      count={data?.length ?? 0}
      emptyLabel="Nothing expiring soon."
    >
      {data?.slice(0, 5).map((c) => (
        <li key={c.id}>
          <Link
            to={`/vendors/${c.vendor_id}`}
            className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {c.vendor_name}
          </Link>{' '}
          <span className="text-xs text-muted">expires {c.expiry_date}</span>
        </li>
      ))}
    </Tile>
  )
}

export function HomeDashboardPage() {
  const { hasRole } = useAuth()
  const showApprovals = hasRole(...APPROVAL_ROLES)
  const showVendorManagement = hasRole(...VENDOR_MANAGEMENT_ROLES)
  const showQuarantine = hasRole(...QUARANTINE_ROLES)
  const showAnyTile = showApprovals || showVendorManagement || showQuarantine

  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Dashboard</PageTitle>
      <p className="mt-1 text-sm text-muted">What needs your attention.</p>

      {!showAnyTile && (
        <p className="mt-4 text-sm text-muted">
          Nothing project-independent needs your attention right now -- check{' '}
          <Link
            to="/"
            className="rounded text-brand underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            your projects
          </Link>{' '}
          for BOQ reconciliation, drawing ingestion, and quote review items (there is no cross-project summary of
          those yet -- each is checked per project today).
        </p>
      )}

      {showAnyTile && (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {showApprovals && <ApprovalsTile />}
          {showQuarantine && <QuarantineTile />}
          {showVendorManagement && <VendorDuplicatesTile />}
          {showVendorManagement && <ExpiringCertificatesTile />}
        </div>
      )}
    </div>
  )
}
