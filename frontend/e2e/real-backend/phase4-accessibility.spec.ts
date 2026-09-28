import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { D1_SIM_PROJECT_CODE, findProjectByCode, loginViaKeycloak } from './helpers'

// Phase 4 (docs/ui-qa-brief.md): @axe-core/playwright run on every restyled
// page, zero serious/critical violations. This chunk covers AppShell (via
// every page below) + the core project pages.
test.describe('Phase 4 accessibility -- core project pages', () => {
  test('ProjectsListPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('ProjectDetailPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('SheetIndexPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    const drawingsResp = await page.request.get(`/api/v1/projects/${project.id}/drawings`)
    const drawings = (await drawingsResp.json()) as { id: string }[]
    test.skip(drawings.length === 0, 'no drawings on this fixture this run')
    await page.goto(`/projects/${project.id}/drawings/${drawings[0].id}`)
    await page.waitForLoadState('domcontentloaded')

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })
})
