import { expect, test } from '@playwright/test'

// Happy path for Phase 8b: an authenticated user sees the projects list
// and can open a project's detail page to see its drawings. Mocks every
// API response rather than needing a live backend + a completed Keycloak
// login (blocked locally by the documented "Cookie not found" HTTP-only
// dev limitation -- see docs/keycloak-setup.md) -- this proves the real
// component/routing/API-client wiring renders correctly against realistic
// response shapes, which is what would actually break if any of them
// drifted out of sync.
test('an authenticated user opens a project and sees its drawings', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sub: 'estimator-1', tenant_id: 'demo', roles: ['estimator'], acr: null }),
    }),
  )
  await page.route('**/api/v1/projects', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'p1',
          code: 'PRJ-1',
          name: 'Demo Tower',
          client_name: 'Acme',
          status: 'active',
          tender_ref: null,
          base_currency: 'AED',
          emirate: 'Dubai',
          area: null,
          latitude: null,
          longitude: null,
          created_at: '2026-01-01T00:00:00Z',
        },
      ]),
    }),
  )
  await page.route('**/api/v1/projects/p1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'p1',
        code: 'PRJ-1',
        name: 'Demo Tower',
        client_name: 'Acme',
        status: 'active',
        tender_ref: null,
        base_currency: 'AED',
        emirate: 'Dubai',
        area: null,
        latitude: null,
        longitude: null,
        created_at: '2026-01-01T00:00:00Z',
      }),
    }),
  )
  await page.route('**/api/v1/projects/p1/drawings', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'd1',
          project_id: 'p1',
          original_filename: 'tender-set.pdf',
          content_type: 'application/pdf',
          kind: 'vector_pdf',
          size_bytes: 1234,
          sha256: '0'.repeat(64),
          sheet_count: 3,
          status: 'ready',
          error_message: null,
          created_at: '2026-01-01T00:00:00Z',
        },
      ]),
    }),
  )

  await page.goto('/')
  await expect(page.getByRole('link', { name: 'PRJ-1' })).toBeVisible()

  await page.getByRole('link', { name: 'PRJ-1' }).click()
  await expect(page.getByRole('heading', { name: 'PRJ-1 -- Demo Tower' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'tender-set.pdf' })).toBeVisible()
  await expect(page.getByText('ready')).toBeVisible()
})
