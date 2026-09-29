import { expect, test } from '@playwright/test'

// AG Grid's own row virtualisation is what "smooth at 4,200+ rows" (the
// brief's own phrasing) actually rests on: only the rows scrolled into
// view are ever mounted in the DOM. This is tested in a real browser
// (Playwright), not vitest+jsdom -- jsdom has no ResizeObserver and no
// real layout engine, so AG Grid's virtualisation math (which depends on
// the container's actual pixel height) cannot be exercised meaningfully
// there. See docs/module-frontend-phase8c-plan.md §2.
function syntheticBoqItem(i: number) {
  return {
    id: `item-${i}`,
    project_id: 'p1',
    parent_id: null,
    item_no: `${i + 1}`,
    description: `Synthetic BOQ line ${i}`,
    uom: 'm2',
    boq_quantity: 100 + i,
    trade_node_id: null,
    level: 0,
    path: `${i + 1}`,
    sort_order: i,
    variance: 0,
    variance_pct: 0,
    discrepancy_class: null,
    reconciliation_note: null,
    reconciled_at: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

test('the reconciliation grid stays virtualised at 5,000 rows', async ({ page }) => {
  const rows = Array.from({ length: 5000 }, (_, i) => syntheticBoqItem(i))

  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sub: 'estimator-1', tenant_id: 'demo', roles: ['estimator'], acr: null }),
    }),
  )
  await page.route('**/api/v1/projects/p1/boq-items', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rows) }),
  )
  await page.route('**/api/v1/projects/p1/measurements:unlinked*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  await page.goto('/projects/p1/boq')
  await expect(page.getByText('Synthetic BOQ line 0')).toBeVisible()

  const rowCount = await page.locator('.ag-row').count()
  expect(rowCount).toBeGreaterThan(0)
  expect(rowCount).toBeLessThan(200) // well under the full 5,000 -- proves virtualisation, not "renders everything"
})

// Found live during the finish-brief follow-up's second walkthrough:
// clicking Accept on a suggested measurement link the backend then 422s
// (e.g. a dimensionally-incompatible unit -- BOQ uom "m3" vs. a length
// measurement) silently did nothing at all, no error shown anywhere --
// the same "an action that can't succeed stays enabled and fails 100%
// silently" bug class flagged repeatedly in docs/ui-qa/issues.md. Fixed
// by rendering linkMeasurement.isError, same pattern as the Reconcile
// button just above it in ItemDetailPanel.
test('a rejected suggested link (422) shows an error, not silence', async ({ page }) => {
  const item = syntheticBoqItem(0)

  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sub: 'estimator-1', tenant_id: 'demo', roles: ['estimator'], acr: null }),
    }),
  )
  await page.route('**/api/v1/projects/p1/boq-items', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([item]) }),
  )
  await page.route('**/api/v1/projects/p1/measurements:unlinked*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route(`**/api/v1/boq-items/${item.id}/measurements`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    }
    // POST: the backend's real validation for a dimensionally-incompatible
    // unit -- see backend/app/services/boq.py -- returned as an RFC 9457
    // problem+json body, exactly as ApiError (frontend/src/lib/api.ts)
    // expects it.
    return route.fulfill({
      status: 422,
      contentType: 'application/problem+json',
      body: JSON.stringify({
        type: 'urn:installtec:validation-error',
        title: 'Validation error',
        status: 422,
        detail: "Cannot link: BOQ uom 'm3' (volume) is not compatible with measurement unit 'm' (length)",
      }),
    })
  })
  await page.route(`**/api/v1/boq-line-items/${item.id}/measurement-suggestions*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { target_id: 'meas-1', fuzzy_score: 0.4, semantic_score: null, combined_score: 0.4, rag_adjustment: 0, final_score: 0.43 },
      ]),
    }),
  )

  await page.goto('/projects/p1/boq')
  await page.getByText('Synthetic BOQ line 0').click()
  await expect(page.getByText('Suggested links')).toBeVisible()
  await page.getByRole('button', { name: 'Accept' }).click()

  await expect(page.getByRole('alert').filter({ hasText: 'not compatible' })).toBeVisible()
  // "None linked yet." must still be showing -- the failed link genuinely
  // never linked anything, so the earlier silent-failure state (indistinguishable
  // from a successful, empty link list) must not be mistaken for success.
  await expect(page.getByText('None linked yet.')).toBeVisible()
})
