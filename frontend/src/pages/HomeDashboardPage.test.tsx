import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApprovalRequestOut } from '../types/api'

let pending: ApprovalRequestOut[] = []
vi.mock('../features/dashboard/api', () => ({
  usePendingApprovalsForMe: () => ({ data: pending, isLoading: false, isError: false }),
  useQuarantineQueueForDashboard: () => ({ data: [], isLoading: false, isError: false }),
  useOpenVendorDuplicatesForDashboard: () => ({ data: [], isLoading: false, isError: false }),
  useExpiringCertificatesForDashboard: () => ({ data: [], isLoading: false, isError: false }),
}))
vi.mock('../features/approvals/api', () => ({ useSubmitterName: () => () => 'someone' }))

import { newestApprovals } from '../lib/approvals'
import { ApprovalsTile } from './HomeDashboardPage'

function request(n: number, requestedAt: string): ApprovalRequestOut {
  return {
    id: `r${n}`, project_id: null, entity_type: 'cost_rate_change', entity_id: `e${n}`, amount: 1000 + n, currency: 'AED',
    status: 'pending', current_seq: 1, requested_by: 'u1', requested_at: requestedAt, completed_at: null, steps: [],
    project_code: null, project_name: null, requested_by_name: null, waiting_role: 'lead_estimator',
    settlement_version_no: null, margin_on_sell_pct: null, view_state: 'actionable', payload_snapshot: null,
  }
}

// n requests, request 1 the oldest, one hour apart
function queue(n: number): ApprovalRequestOut[] {
  return Array.from({ length: n }, (_, i) => request(i + 1, new Date(Date.UTC(2026, 9, 1, i)).toISOString()))
}

function renderTile() {
  return render(
    <MemoryRouter>
      <ApprovalsTile />
    </MemoryRouter>,
  )
}

describe('newestApprovals', () => {
  it('orders by requested_at, newest first, and caps the rows', () => {
    const shuffled = [...queue(8)].reverse().sort((a, b) => (a.id < b.id ? 1 : -1))
    expect(newestApprovals(shuffled).map((r) => r.id)).toEqual(['r8', 'r7', 'r6', 'r5', 'r4'])
  })

  it('does not mutate its input', () => {
    const input = queue(7)
    const before = input.map((r) => r.id)
    newestApprovals(input)
    expect(input.map((r) => r.id)).toEqual(before)
  })
})

describe('ApprovalsTile', () => {
  beforeEach(() => {
    pending = []
  })

  it('shows the empty state with no count link', () => {
    renderTile()
    expect(screen.getByText('Nothing waiting on your decision.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /View all/ })).not.toBeInTheDocument()
  })

  it('with at most 5 pending shows them all and a View all link with the total, no "newest of" note', () => {
    pending = queue(3)
    renderTile()
    expect(screen.getByRole('heading', { name: /Approvals waiting for me/ })).toHaveTextContent('(3)')
    expect(screen.getAllByRole('listitem').filter((li) => li.querySelector('a[href^="/approvals/"]'))).toHaveLength(3)
    expect(screen.queryByText(/newest of/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View all 3' })).toHaveAttribute('href', '/approvals')
  })

  it('with more than 5 pending shows the 5 newest, the total, and View all; the newest request is never hidden', () => {
    pending = queue(18) // r18 is the one just created
    renderTile()
    const tile = screen.getByRole('heading', { name: /Approvals waiting for me/ }).parentElement as HTMLElement
    expect(within(tile).getByRole('heading')).toHaveTextContent('(18)')
    const rows = within(tile).getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/approvals/'))
    expect(rows).toHaveLength(5)
    expect(rows[0]).toHaveTextContent('AED 1,018.00') // the newest first
    expect(within(tile).queryByText('AED 1,001.00')).not.toBeInTheDocument() // the oldest is left to /approvals
    expect(within(tile).getByText('Showing the 5 newest of 18.')).toBeInTheDocument()
    expect(within(tile).getByRole('link', { name: 'View all 18' })).toHaveAttribute('href', '/approvals')
  })
})
