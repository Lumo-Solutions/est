import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { SkeletonRows } from '../components/Skeleton'
import {
  useExpiringCertificatesForDashboard,
  useOpenVendorDuplicatesForDashboard,
  usePendingApprovalsForMe,
  useQuarantineQueueForDashboard,
} from '../features/dashboard/api'
import { formatMoney } from '../lib/format'
import { Role } from '../lib/roles'

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
    <div className="rounded border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-800">
        {/* text-slate-400 measured 2.63:1 via axe on the sidebar's own
            section label in an earlier Phase 4 chunk (AppShell) -- same
            failure mode here, same fix. */}
        {title} {!isLoading && !isError && <span className="text-slate-600">({count})</span>}
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
      {!isLoading && !isError && count === 0 && <p className="mt-2 text-sm text-slate-500">{emptyLabel}</p>}
      {!isLoading && !isError && count > 0 && <ul className="mt-2 space-y-1 text-sm">{children}</ul>}
    </div>
  )
}

function ApprovalsTile() {
  const { data, isLoading, isError, error } = usePendingApprovalsForMe()
  return (
    <Tile
      title="Approvals waiting for me"
      isLoading={isLoading}
      isError={isError}
      errorMessage={error?.message}
      count={data?.length ?? 0}
      emptyLabel="Nothing waiting on your decision."
    >
      {data?.map((r) => (
        <li key={r.id} className="flex items-center justify-between">
          <span>
            {r.entity_type} -- {formatMoney(r.amount, r.currency)}
          </span>
          <span className="text-xs text-slate-500">step {r.current_seq}</span>
        </li>
      ))}
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
            className="rounded text-slate-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
            className="rounded text-slate-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
            className="rounded text-slate-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {c.vendor_name}
          </Link>{' '}
          <span className="text-xs text-slate-500">expires {c.expiry_date}</span>
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
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Dashboard</h1>
      <p className="mt-1 text-sm text-slate-500">What needs your attention.</p>

      {!showAnyTile && (
        <p className="mt-4 text-sm text-slate-500">
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
