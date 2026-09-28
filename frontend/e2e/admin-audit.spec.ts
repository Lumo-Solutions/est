import { expect, test } from '@playwright/test'

// Happy path for Phase 8f: an authenticated managing_director sees the
// admin taxonomy tab and the audit viewer, both rendering real API data.
test('admin taxonomy tab and audit viewer render real data', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sub: 'md-1', tenant_id: 'demo', roles: ['managing_director'], acr: 'silver' }),
    }),
  )
  await page.route('**/api/v1/taxonomy*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 't1', parent_id: null, code: 'EARTH', name: 'Earthworks', level: 0, path: 't1',
          sort_order: 0, is_active: true, attributes: null,
          created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
        },
      ]),
    }),
  )
  await page.route('**/api/v1/audit/events*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1, occurred_at: '2026-01-01T00:00:00Z', actor_sub: 'md-1', actor_roles: ['managing_director'],
          action: 'create', entity_type: 'approval_policy', entity_id: 'p1', project_id: null,
          ip_address: '127.0.0.1', seq: 1, event_hash: 'a'.repeat(64),
        },
      ]),
    }),
  )

  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible()
  await expect(page.getByText('Earthworks', { exact: true })).toBeVisible()

  await page.goto('/audit')
  await expect(page.getByRole('heading', { name: 'Audit viewer' })).toBeVisible()
  await expect(page.getByText('approval_policy:p1')).toBeVisible()
})
