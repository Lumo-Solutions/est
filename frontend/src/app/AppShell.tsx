import { NavLink, Outlet, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DevMfaBanner } from '../components/DevMfaBanner'
import { logout } from '../lib/api'
import { Role } from '../lib/roles'

export interface NavItem {
  label: string
  to: string
  requiresRoles?: string[]
  // Match only the exact path. Needed on any item whose path is a prefix of
  // its siblings' (Projects '/', a project's Overview) or it stays highlighted
  // alongside them on every sub-page.
  end?: boolean
}

export function filterVisibleNavItems(items: NavItem[], hasRole: (...roles: string[]) => boolean): NavItem[] {
  return items.filter((item) => !item.requiresRoles || hasRole(...item.requiresRoles))
}

// Role-aware visibility only -- purely a UX nicety, the server is the only
// real enforcement (see docs/preconstruction-build-brief.md Phase 8).
function projectNavItems(projectId: string): NavItem[] {
  return [
    { label: 'Overview', to: `/projects/${projectId}`, end: true },
    { label: 'Drawings', to: `/projects/${projectId}/drawings` },
    { label: 'Typology', to: `/projects/${projectId}/typology` },
    { label: 'BOQ', to: `/projects/${projectId}/boq` },
    {
      label: 'Procurement',
      to: `/projects/${projectId}/procurement/packages`,
      requiresRoles: [Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD],
    },
    {
      // backend/app/api/v1/routes/settlement.py's _LINE_ROLES grants
      // simulate/line-edit/scenario/export access to all 5 business roles,
      // not just the 3 that can build/submit a draft (_HEADER_ROLES) --
      // the nav gate previously only matched _HEADER_ROLES minus estimator,
      // so estimator/procurement_head had real server-granted access to
      // this page with no nav link to reach it (docs/ui-qa/issues.md
      // UI-P2-023).
      label: 'Settlement',
      to: `/projects/${projectId}/settlement`,
      requiresRoles: [
        Role.ESTIMATOR,
        Role.LEAD_ESTIMATOR,
        Role.PROCUREMENT_HEAD,
        Role.BD_DIRECTOR,
        Role.MANAGING_DIRECTOR,
      ],
    },
    { label: 'Export', to: `/projects/${projectId}/export` },
    { label: 'Win/loss', to: `/projects/${projectId}/win-loss` },
    // module_e.py's endpoints are all CurrentUser (any role), read-only.
    { label: 'Post-award', to: `/projects/${projectId}/module-e` },
  ]
}

// platform_admin is deliberately absent from Admin and Audit below (but see
// the Inbox item further down, which is the one deliberate exception): it's
// a narrow, Keycloak-only role scoped to the quarantine queue's
// tenant-resolution action (docs/ui-qa/coverage.md's role glossary), not a
// general admin persona. None of Admin's six tabs or Audit's endpoints grant
// it any read or write access server-side -- the nav previously linked it to
// two destinations that were either fully read-only-looking-but-broken or a
// guaranteed 403 on load (docs/ui-qa/issues.md UI-P2-022).
const GLOBAL_NAV_ITEMS: NavItem[] = [
  { label: 'Projects', to: '/' },
  // No requiresRoles: HomeDashboardPage checks per-tile roles itself and
  // shows a sensible message for a role with no cross-project tile (an
  // estimator, whose relevant items are all project-scoped today).
  { label: 'Dashboard', to: '/dashboard' },
  // No requiresRoles: reading the vendor directory is useful to every role
  // (matches GET /vendors's own "any authenticated user" server check) --
  // only the write actions inside VendorsPage/VendorDetailPage are gated.
  { label: 'Vendors', to: '/vendors' },
  // Same reasoning as Vendors above: GET /cost-items has no role
  // restriction server-side, only create/record-rate do.
  { label: 'Cost library', to: '/cost-library' },
  { label: 'Admin', to: '/admin', requiresRoles: [Role.MANAGING_DIRECTOR] },
  { label: 'Audit', to: '/audit', requiresRoles: [Role.MANAGING_DIRECTOR, Role.BD_DIRECTOR] },
  {
    // platform_admin IS included here, unlike the rest of this array --
    // deliberately, not an oversight. Its one and only exclusive action
    // anywhere in the app ("Resolve tenant" on an unknown-tenant
    // quarantined email) lives exclusively on this page, so it must be
    // able to reach it via nav. Do not "fix" this back to match the usual
    // platform_admin-excluded pattern above.
    label: 'Inbox',
    to: '/inbox',
    requiresRoles: [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.PLATFORM_ADMIN],
  },
]

// docs/ui-design-system.md section 4.1 -- active item gets the brand tint,
// not the old plain-dark-fill default. Link text/hrefs are untouched by
// this pass (every existing e2e spec locates nav by getByRole('link',
// {name}), which is layout-agnostic), only the visual treatment and the
// vertical (sidebar) vs horizontal (old top-bar) arrangement changed.
function NavList({ items, hasRole }: { items: NavItem[]; hasRole: (...roles: string[]) => boolean }) {
  return (
    <>
      {filterVisibleNavItems(items, hasRole).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end ?? item.to === '/'}
          className={({ isActive }) =>
            `block rounded px-3 py-1.5 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
              isActive
                ? 'border-l-2 border-brand bg-brand-subtle font-medium text-brand'
                : 'border-l-2 border-transparent text-slate-600 hover:bg-slate-100'
            }`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </>
  )
}

// docs/ui-design-system.md section 4.1: a fixed-width sidebar (240px at
// >=1280px) replaces the old single horizontal nav bar -- chosen because
// every existing page's own content already assumes a `flex-1` main area
// with no left inset, so a sidebar is a wrapper-only change, not a
// per-page one. Deliberately NOT adding a project-name header block
// above the project nav (the design doc's own suggestion) in this pass:
// that needs a `useProject(projectId)` fetch inside the shell that runs
// on every single page in the app, which is a real new data dependency
// with its own loading/error shape to get right, not a pure style change
// -- left as a follow-up rather than folded into a restyle pass. Also
// deliberately NOT adding a shared breadcrumb component in the top bar:
// Phases 2/3 already decided per-page back-links over a shared breadcrumb
// (docs/ui-qa/issues.md UI-P2-004), and revisiting that is a bigger
// decision than this pass's scope.
export function AppShell() {
  const { user, hasRole } = useAuth()
  const { projectId } = useParams()

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <span className="text-sm font-semibold text-slate-800">InstallTec Estimating</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
          <NavList items={GLOBAL_NAV_ITEMS} hasRole={hasRole} />
          {projectId && (
            <>
              <div className="mt-3 border-t border-slate-200 pt-3">
                {/* slate-400 measured at 2.63:1 on white via axe (Phase 4 QA) --
                    fails AA's 4.5:1 text minimum; slate-600 clears it with
                    margin (slate-500 is too close to the boundary to trust
                    without measuring). */}
                <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-slate-600">Project</p>
                <NavList items={projectNavItems(projectId)} hasRole={hasRole} />
              </div>
            </>
          )}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <DevMfaBanner active={user?.mfaDisabledDev === true} />
        <header className="flex h-14 shrink-0 items-center justify-end border-b border-slate-200 bg-white px-4">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            {user && <span title={user.sub}>{user.username ?? user.sub}</span>}
            <button
              type="button"
              onClick={() => logout()}
              className="rounded text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
