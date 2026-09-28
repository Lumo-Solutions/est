import { expect, test } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// Phase 3 gap-fill (docs/ui-qa-brief.md): cost library and Module E were
// confirmed "no UI at all" capabilities (docs/ui-qa/coverage.md section 2).
// This exercises the new CostLibraryPage/CostItemDetailPage/ModuleEPage
// against the real backend.

test.describe('CostLibraryPage', () => {
  test('estimator sees the cost item list read-only, and a direct create attempt 403s server-side', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    await page.goto('/cost-library')
    await expect(page.getByRole('heading', { name: 'Cost library' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'New cost item' })).toHaveCount(0)

    const response = await page.request.post('/api/v1/cost-items', {
      headers: await csrfHeaders(page),
      data: { code: 'SHOULD-403', description: 'x', uom: 'm3' },
    })
    expect(response.status()).toBe(403)
  })

  test('lead_estimator can create a cost item, record a rate, and see it as-of today', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/cost-library')
    await page.getByRole('button', { name: 'New cost item' }).click()

    const uniqueCode = `E2E-${Date.now()}`
    await page.getByLabel('Code').fill(uniqueCode)
    await page.getByLabel('Description').fill('E2E cost item')
    await page.getByLabel('UoM').fill('m3')
    await page.getByRole('button', { name: 'Create item' }).click()

    await expect(page.getByRole('link', { name: uniqueCode })).toBeVisible()
    await page.getByRole('link', { name: uniqueCode }).click()
    await expect(page.getByRole('heading', { name: `${uniqueCode} — E2E cost item` })).toBeVisible()
    await expect(page.getByText(/No rate was on file/)).toBeVisible()

    await page.getByRole('button', { name: 'Record new rate' }).click()
    await page.getByLabel('Component type').fill('material')
    await page.getByLabel('Description', { exact: true }).last().fill('E2E component')
    await page.getByLabel('Unit cost').fill('42.50')
    await page.getByRole('button', { name: 'Save rate' }).click()

    // Phase 4 design-system pass (docs/ui-design-system.md) started using
    // the shared formatMoney helper for the component table's unit
    // cost/amount too, not just the rate summary -- both now correctly
    // show "AED 42.50", not just a bare "42.50" as before, which is the
    // right behavior but means the summary line is no longer the only
    // match for this text. Scope to the summary paragraph specifically.
    await expect(page.getByText('AED 42.50').first()).toBeVisible()
    await expect(page.getByText('AED 42.50')).toHaveCount(3) // summary + unit cost + amount cells
    await expect(page.getByText('E2E component')).toBeVisible()
  })
})

test.describe('ModuleEPage', () => {
  test('reads all four tabs without console/network errors', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const projectsResponse = await page.request.get('/api/v1/projects')
    const projects = (await projectsResponse.json()) as { id: string; code: string }[]
    const project = projects[0]
    test.skip(!project, 'no seeded project available this run')
    if (!project) return

    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    await page.goto(`/projects/${project.id}/module-e`)
    await expect(page.getByRole('heading', { name: 'Post-award (Module E)' })).toBeVisible()

    for (const tabName of ['BOQ revisions', 'Exclusion register', 'Outturn costs', 'Contracts']) {
      await page.getByRole('button', { name: tabName }).click()
      // Every tab renders a specific empty-state sentence when there's no
      // data for this seeded project, or real rows if there are -- either
      // way it should never still say "Loading..." a moment later.
      await expect(page.getByText('Loading...')).toHaveCount(0)
    }

    expect(consoleErrors).toEqual([])
  })
})
