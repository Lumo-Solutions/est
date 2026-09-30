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
  // ProjectsListPage uses the paginated GET /projects?limit=&offset=
  // path (useProjectsPage -> the Page envelope), not the bare unpaginated
  // array useProjects() (no args) still returns -- see
  // frontend/src/features/projects/api.ts. The route pattern needs the
  // trailing `*` to match the query string at all; without it this mock
  // was silently never intercepting the request the page actually makes
  // (found live: this test started failing -- "PRJ-1" never appeared --
  // the moment ProjectsListPage switched to the paginated hook).
  await page.route('**/api/v1/projects?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
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
        ],
        total: 1,
        limit: 20,
        offset: 0,
      }),
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
  await page.route('**/api/v1/projects/p1/members', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/tender-classes', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ code: 'drawing', label: 'Drawing', default_label: 'Drawing', enabled: true, sort_order: 0 }]),
    }),
  )
  // The project page is one page: header, then the AI-sorted document tree (GET .../tender-documents/tree).
  await page.route('**/api/v1/projects/p1/tender-documents/tree', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'd1', package_id: 'k1', name: 'tender-set.pdf', path: 'Tender/tender-set.pdf', ext: 'pdf', size_bytes: 1234,
            doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'general_arrangement', unit_type: null,
            document_number: 'C-101', title: 'Road layout', revision: 'A', sheet_number: null, scale: '1:500', confidence: 0.97,
            status: 'routed', display_status: 'ready', status_reason: null, classified_by: 'ai', decided_by: 'ai', auto_accepted: true,
            flags: [], routed_kind: 'drawing', drawing_id: 'dr1', evidence_quote: 'DRAWING NO: C-101', evidence_page: 1, ai_note: null,
            supersedes: [], created_at: '2026-01-01T00:00:00Z',
          },
        ],
        summary: {
          total: 1, by_display_status: { ready: 1 }, by_class: { drawing: 1 }, needs_check: 0, in_progress: 0, drawings_total: 1,
          drawings_ready: 1, boq_documents: [], addenda: 0, packages_processing: 0, auto_accept_min: 0.85, ai_available: true, ai_message: null,
        },
      }),
    }),
  )

  await page.goto('/')
  await expect(page.getByRole('link', { name: 'PRJ-1' })).toBeVisible()

  await page.getByRole('link', { name: 'PRJ-1' }).click()
  await expect(page.getByRole('heading', { name: 'PRJ-1 -- Demo Tower' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Drawing, 1 file' })).toBeVisible()
  await expect(page.getByText('tender-set.pdf')).toBeVisible()
  await expect(page.getByText('1 of 1 drawings ready')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Edit project' })).toBeVisible()
})
