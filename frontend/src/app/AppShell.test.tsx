import { describe, expect, it } from 'vitest'
import { filterVisibleNavItems, type NavItem } from './AppShell'
import { Role } from '../lib/roles'

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
