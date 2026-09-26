import { NavLink, Outlet, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { logout } from '../lib/api'
import { Role } from '../lib/roles'

export interface NavItem {
  label: string
  to: string
  requiresRoles?: string[]
}

export function filterVisibleNavItems(items: NavItem[], hasRole: (...roles: string[]) => boolean): NavItem[] {
  return items.filter((item) => !item.requiresRoles || hasRole(...item.requiresRoles))
}

// Role-aware visibility only -- purely a UX nicety, the server is the only
// real enforcement (see docs/preconstruction-build-brief.md Phase 8).
function projectNavItems(projectId: string): NavItem[] {
  return [
    { label: 'Overview', to: `/projects/${projectId}` },
    { label: 'Drawings', to: `/projects/${projectId}/drawings` },
    { label: 'Typology', to: `/projects/${projectId}/typology` },
    { label: 'BOQ', to: `/projects/${projectId}/boq` },
    {
      label: 'Procurement',
      to: `/projects/${projectId}/procurement/packages`,
      requiresRoles: [Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD],
    },
    {
      label: 'Settlement',
      to: `/projects/${projectId}/settlement`,
      requiresRoles: [Role.LEAD_ESTIMATOR, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR],
    },
    { label: 'Export', to: `/projects/${projectId}/export` },
    { label: 'Win/loss', to: `/projects/${projectId}/win-loss` },
  ]
}

const GLOBAL_NAV_ITEMS: NavItem[] = [
  { label: 'Projects', to: '/' },
  { label: 'Admin', to: '/admin', requiresRoles: [Role.PLATFORM_ADMIN, Role.MANAGING_DIRECTOR] },
  { label: 'Audit', to: '/audit', requiresRoles: [Role.PLATFORM_ADMIN, Role.MANAGING_DIRECTOR, Role.BD_DIRECTOR] },
]

function NavList({ items, hasRole }: { items: NavItem[]; hasRole: (...roles: string[]) => boolean }) {
  return (
    <>
      {filterVisibleNavItems(items, hasRole).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `rounded px-3 py-1.5 text-sm ${
                isActive ? 'bg-slate-800 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
    </>
  )
}

export function AppShell() {
  const { user, hasRole } = useAuth()
  const { projectId } = useParams()

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <nav className="flex items-center gap-1">
          <NavList items={GLOBAL_NAV_ITEMS} hasRole={hasRole} />
          {projectId && (
            <>
              <span className="mx-2 text-slate-300">|</span>
              <NavList items={projectNavItems(projectId)} hasRole={hasRole} />
            </>
          )}
        </nav>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          {user && <span>{user.sub}</span>}
          <button type="button" onClick={() => logout()} className="text-slate-500 hover:text-slate-800">
            Sign out
          </button>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
