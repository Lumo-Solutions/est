import { useState } from 'react'
import {
  Calculator,
  ClipboardList,
  CheckCircle2,
  Coins,
  Download,
  FolderKanban,
  HardHat,
  Inbox,
  LayoutDashboard,
  LogOut,
  Handshake,
  PencilRuler,
  ScrollText,
  Settings,
  Shapes,
  ShoppingCart,
  Store,
  Table2,
  Trophy,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Avatar } from '../components/Avatar'
import { DevMfaBanner } from '../components/DevMfaBanner'
import { PageTitleSlotContext } from '../components/pageTitleContext'
import { logout } from '../lib/api'
import { Role } from '../lib/roles'

export interface NavItem {
  label: string
  to: string
  // Decorative (aria-hidden) -- the link's accessible name is still `label`,
  // which every e2e spec locates by (getByRole('link', { name })).
  icon?: LucideIcon
  requiresRoles?: string[]
  // Match only the exact path. Needed on any item whose path is a prefix of
  // its siblings' (Projects '/', a project's page) or it stays highlighted
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
    { label: 'Project', icon: ClipboardList, to: `/projects/${projectId}`, end: true },
    { label: 'Drawings', icon: PencilRuler, to: `/projects/${projectId}/drawings` },
    { label: 'Typology', icon: Shapes, to: `/projects/${projectId}/typology` },
    { label: 'BOQ', icon: Table2, to: `/projects/${projectId}/boq` },
    {
      label: 'Procurement',
      icon: ShoppingCart,
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
      icon: Calculator,
      to: `/projects/${projectId}/settlement`,
      requiresRoles: [
        Role.ESTIMATOR,
        Role.LEAD_ESTIMATOR,
        Role.PROCUREMENT_HEAD,
        Role.BD_DIRECTOR,
        Role.MANAGING_DIRECTOR,
      ],
    },
    { label: 'Export', icon: Download, to: `/projects/${projectId}/export` },
    { label: 'Win/loss', icon: Trophy, to: `/projects/${projectId}/win-loss` },
    // module_e.py's endpoints are all CurrentUser (any role), read-only.
    { label: 'Post-award', icon: Handshake, to: `/projects/${projectId}/module-e` },
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
  { label: 'Projects', icon: FolderKanban, to: '/' },
  // No requiresRoles: HomeDashboardPage checks per-tile roles itself and
  // shows a sensible message for a role with no cross-project tile (an
  // estimator, whose relevant items are all project-scoped today).
  { label: 'Dashboard', icon: LayoutDashboard, to: '/dashboard' },
  // Same roles as the dashboard's approvals tile and GET /approvals/inbox.
  {
    label: 'Approvals',
    icon: CheckCircle2,
    to: '/approvals',
    requiresRoles: [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR],
  },
  // No requiresRoles: reading the vendor directory is useful to every role
  // (matches GET /vendors's own "any authenticated user" server check) --
  // only the write actions inside VendorsPage/VendorDetailPage are gated.
  { label: 'Vendors', icon: Store, to: '/vendors' },
  // Same reasoning as Vendors above: GET /cost-items has no role
  // restriction server-side, only create/record-rate do.
  { label: 'Cost library', icon: Coins, to: '/cost-library' },
  { label: 'Admin', icon: Settings, to: '/admin', requiresRoles: [Role.MANAGING_DIRECTOR] },
  { label: 'Audit', icon: ScrollText, to: '/audit', requiresRoles: [Role.MANAGING_DIRECTOR, Role.BD_DIRECTOR] },
  {
    // platform_admin IS included here, unlike the rest of this array --
    // deliberately, not an oversight. Its one and only exclusive action
    // anywhere in the app ("Resolve tenant" on an unknown-tenant
    // quarantined email) lives exclusively on this page, so it must be
    // able to reach it via nav. Do not "fix" this back to match the usual
    // platform_admin-excluded pattern above.
    label: 'Inbox',
    icon: Inbox,
    to: '/inbox',
    requiresRoles: [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.PLATFORM_ADMIN],
  },
]

// docs/figma-implementation-plan.md 3.1 -- Figma's active state: a 6px brand
// bar on the sidebar's left edge (rounded on its right corners) + brand text;
// inactive items use --color-muted (Figma's #B1B1B1 is 2.14:1, fails AA).
// Link text/hrefs are untouched (every existing e2e spec locates nav by
// getByRole('link', {name}), which is layout-agnostic).
function NavList({ items, hasRole }: { items: NavItem[]; hasRole: (...roles: string[]) => boolean }) {
  return (
    <>
      {filterVisibleNavItems(items, hasRole).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end ?? item.to === '/'}
          className={({ isActive }) =>
            `relative flex items-center gap-3 rounded-control px-4 py-2.5 text-base font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 ${
              isActive ? 'text-brand' : 'text-muted hover:bg-canvas hover:text-brand'
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <span aria-hidden="true" className="absolute -left-4 top-0 h-full w-1.5 rounded-r-bar bg-brand" />
              )}
              {item.icon && <item.icon aria-hidden="true" className="h-6 w-6 shrink-0" />}
              {item.label}
            </>
          )}
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
  // The header slot the page <h1> is portalled into (components/PageTitle).
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null)
  const displayName = user?.username ?? user?.sub ?? ''

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <aside className="flex w-[230px] shrink-0 flex-col border-r border-hairline bg-white xl:w-[250px]">
        <div className="flex h-20 shrink-0 items-center gap-3 px-6 xl:h-[100px]">
          <HardHat aria-hidden="true" className="h-8 w-8 shrink-0 text-brand" />
          <span className="text-lg font-bold leading-tight text-ink-title">InstallTec Estimating</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-4 pb-4">
          <NavList items={GLOBAL_NAV_ITEMS} hasRole={hasRole} />
          {projectId && (
            <>
              <div className="mt-3 border-t border-hairline pt-3">
                {/* slate-400 measured at 2.63:1 on white via axe (Phase 4 QA) --
                    fails AA's 4.5:1 text minimum; --color-muted clears it
                    (5.06:1, locked by src/test/tokens.contrast.test.ts). */}
                <p className="px-4 pb-1 text-xs font-medium uppercase tracking-wide text-muted">Project</p>
                <NavList items={projectNavItems(projectId)} hasRole={hasRole} />
              </div>
            </>
          )}
        </nav>
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <DevMfaBanner active={user?.mfaDisabledDev === true} />
        <header className="flex h-20 shrink-0 items-center gap-4 border-b border-hairline bg-white px-6 xl:h-[100px] xl:px-10">
          <div ref={setTitleSlot} className="min-w-0 flex-1" />
          <div className="flex shrink-0 items-center gap-3 text-base text-ink-2">
            {user && (
              <>
                <Avatar name={displayName} />
                <span title={user.sub}>{displayName}</span>
              </>
            )}
            <button
              type="button"
              onClick={() => logout()}
              className="inline-flex items-center gap-2 rounded-pill border border-outline px-4 py-2 text-sm font-medium text-ink-2 hover:border-brand hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <PageTitleSlotContext.Provider value={titleSlot}>
            <Outlet />
          </PageTitleSlotContext.Provider>
        </main>
      </div>
    </div>
  )
}
