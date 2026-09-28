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

test.describe('Phase 4 accessibility -- vendor and typology/BOQ pages', () => {
  test('VendorsPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/vendors')
    await expect(page.getByRole('heading', { name: 'Vendors' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('TypologyPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/typology`)
    await expect(page.getByRole('heading', { name: 'Typology cluster review' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })
})

test.describe('Phase 4 accessibility -- cost library pages', () => {
  test('CostLibraryPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/cost-library')
    await expect(page.getByRole('heading', { name: 'Cost library' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })
})

// Phase 4 (docs/ui-qa-brief.md): ProcurementPackagesPage, QuarantineQueuePage,
// QuoteReviewPage, BidLevelingPage, ExportPage, WinLossPage. QuoteReviewPage
// and BidLevelingPage select a real package/RFQ first so the axe scan covers
// the rendered quotation cards/bid matrix, not just the empty pickers.
const D1_SIM_PACKAGE_LABEL = 'D1 Simulation Package'

test.describe('Phase 4 accessibility -- procurement, quotation and settlement pages', () => {
  test('ProcurementPackagesPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/packages`)
    await expect(page.getByRole('heading', { name: 'Procurement packages and RFQs' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('QuarantineQueuePage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/quarantine`)
    await expect(page.getByRole('heading', { name: 'Quarantine and review queue' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('QuoteReviewPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/procurement/quotes`)
    await expect(page.getByRole('heading', { name: 'Quote review and acceptance' })).toBeVisible()
    await page.locator('select').first().selectOption({ label: D1_SIM_PACKAGE_LABEL })
    await page.locator('select').nth(1).selectOption({ index: 1 })

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('BidLevelingPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/procurement/bid-leveling`)
    await expect(page.getByRole('heading', { name: 'Bid-leveling matrix' })).toBeVisible()
    await page.locator('select').selectOption({ label: D1_SIM_PACKAGE_LABEL })

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('ExportPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/export`)
    await expect(page.getByRole('heading', { name: 'Export' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('WinLossPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/win-loss`)
    await expect(page.getByRole('heading', { name: 'Win / loss' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  // SettlementPage.tsx -- last Phase 4 page-restyle chunk. bd1 has read/
  // submit access to D1-SIM's current settlement (whatever lifecycle state
  // it's in from other specs run this session), which is enough to render
  // the cockpit's status badge, live-simulation panel, and (role-permitting)
  // the trade/line override panels -- exercising the real restyled markup,
  // not just an empty shell.
  test('SettlementPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/settlement`)
    await expect(page.getByRole('heading', { name: 'Settlement cockpit' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })
})

// Phase 4 (docs/ui-qa-brief.md): AdminPage (all six tabs) + AuditPage +
// ModuleEPage + HomeDashboardPage -- the platform-admin/read-heavy chunk.
// managing_director has write access on every Admin tab (see
// admin-audit-permissions.spec.ts), so scanning as md1 exercises each tab's
// write controls, not just its read-only fallback text.
test.describe('Phase 4 accessibility -- admin, audit, Module E and dashboard pages', () => {
  test('AdminPage has no serious/critical axe violations on any of its six tabs', async ({ page }) => {
    await loginViaKeycloak(page, 'md1', 'Md1Pass!')
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible()

    for (const tabName of [
      'Taxonomy',
      'Approval policies',
      'Tolerances',
      'Layer/trade mapping',
      'Reason codes',
      'Vendor regions',
    ]) {
      await page.getByRole('button', { name: tabName }).click()
      const results = await new AxeBuilder({ page }).analyze()
      const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      expect(serious, `${tabName}: ${JSON.stringify(serious, null, 2)}`).toEqual([])
    }
  })

  test('AuditPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'md1', 'Md1Pass!')
    await page.goto('/audit')
    await expect(page.getByRole('heading', { name: 'Audit viewer' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })

  test('ModuleEPage has no serious/critical axe violations on any of its four tabs', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await page.goto(`/projects/${project.id}/module-e`)
    await expect(page.getByRole('heading', { name: 'Post-award (Module E)' })).toBeVisible()

    for (const tabName of ['Contracts', 'BOQ revisions', 'Exclusion register', 'Outturn costs']) {
      await page.getByRole('button', { name: tabName }).click()
      const results = await new AxeBuilder({ page }).analyze()
      const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      expect(serious, `${tabName}: ${JSON.stringify(serious, null, 2)}`).toEqual([])
    }
  })

  test('HomeDashboardPage has no serious/critical axe violations', async ({ page }) => {
    await loginViaKeycloak(page, 'md1', 'Md1Pass!')
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  })
})
