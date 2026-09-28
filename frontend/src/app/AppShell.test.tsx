import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell, filterVisibleNavItems, type NavItem } from './AppShell'
import { Role } from '../lib/roles'

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: { sub: 'c132185e-uuid', username: 'md1', tenantId: 't', roles: [Role.MANAGING_DIRECTOR], acr: null, mfaDisabledDev: false },
    hasRole: () => true,
  }),
}))

const items: NavItem[] = [
  { label: 'Projects', to: '/' },
  { label: 'Admin', to: '/admin', requiresRoles: [Role.PLATFORM_ADMIN, Role.MANAGING_DIRECTOR] },
]

describe('filterVisibleNavItems', () => {
  it('keeps items with no role requirement regardless of the caller role', () => {
    const visible = filterVisibleNavItems(items, () => false)
    expect(visible.map((i) => i.label)).toEqual(['Projects'])
  })

  it('includes a gated item once the caller has one of its required roles', () => {
    const visible = filterVisibleNavItems(items, (...roles) => roles.includes(Role.MANAGING_DIRECTOR))
    expect(visible.map((i) => i.label)).toEqual(['Projects', 'Admin'])
  })
})

function renderShellAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/projects/:projectId/*" element={<div />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  it('highlights only Drawings, not Overview as well, on a drawings sub-page', () => {
    renderShellAt('/projects/p1/drawings/d1')
    expect(screen.getByRole('link', { name: 'Drawings' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('highlights Overview on the project overview page itself', () => {
    renderShellAt('/projects/p1')
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  })

  it('shows the login name in the header, keeping the UUID only as a tooltip', () => {
    renderShellAt('/projects/p1')
    const name = screen.getByText('md1')
    expect(name).toBeInTheDocument()
    expect(name).toHaveAttribute('title', 'c132185e-uuid')
    expect(screen.queryByText('c132185e-uuid')).not.toBeInTheDocument()
  })
})
