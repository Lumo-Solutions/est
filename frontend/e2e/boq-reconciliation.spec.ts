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
