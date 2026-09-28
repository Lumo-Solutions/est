import { expect, test } from '@playwright/test'
import { D1_SIM_PROJECT_CODE, findProjectByCode, loginViaKeycloak } from './helpers'

// Phase 4 close-out (docs/finish-brief.md step 2): every page at 1440, 1280
// and 1024 px wide. Fails on page-level horizontal overflow (the document
// scrolls sideways) and writes a viewport screenshot per page and width to
// docs/ui-qa/screenshots/phase-4/. md1 can reach every page.
const WIDTHS = [1440, 1280, 1024]
const SHOT_DIR = '../docs/ui-qa/screenshots/phase-4'

test.setTimeout(900_000)

test('every page lays out at 1440 / 1280 / 1024 without horizontal page overflow', async ({ page }) => {
  await loginViaKeycloak(page, 'md1', 'Md1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
  const p = `/projects/${project.id}`

  const vendors = (await (await page.request.get('/api/v1/vendors?limit=1')).json()) as { items: { id: string }[] }
  const costItems = (await (await page.request.get('/api/v1/cost-items?limit=1')).json()) as { items: { id: string }[] }

  const pages: [string, string][] = [
    ['projects-list', '/'],
    ['dashboard', '/dashboard'],
    ['vendors', '/vendors'],
    ['vendor-duplicates', '/vendors/duplicates'],
    ['cost-library', '/cost-library'],
    ['project-detail', p],
    ['typology', `${p}/typology`],
    ['boq-import', `${p}/boq/import`],
    ['boq-reconciliation', `${p}/boq`],
    ['procurement-packages', `${p}/procurement/packages`],
    ['quarantine', `${p}/procurement/quarantine`],
    ['quote-review', `${p}/procurement/quotes`],
    ['bid-leveling', `${p}/procurement/bid-leveling`],
    ['settlement', `${p}/settlement`],
    ['export', `${p}/export`],
    ['win-loss', `${p}/win-loss`],
    ['module-e', `${p}/module-e`],
    ['admin', '/admin'],
    ['audit', '/audit'],
    ['not-found', '/no-such-page'],
  ]
  if (vendors.items[0]) pages.push(['vendor-detail', `/vendors/${vendors.items[0].id}`])
  if (costItems.items[0]) pages.push(['cost-item-detail', `/cost-library/${costItems.items[0].id}`])
  // GEO-TEST's fixture drawing has real sheets (D1-SIM's may not) -- same
  // ids project-pages.spec.ts uses.
  const geo = '/projects/cef24c29-5a75-435e-9c78-11a19b115a2f/drawings/747f76c1-24f6-43c9-b75a-29e3ead382cb'
  pages.push(['sheet-index', geo])
  pages.push(['takeoff-viewer', `${geo}/sheets/0`])

  const overflows: string[] = []
  for (const [name, path] of pages) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 800 })
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(400)
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }))
      if (scrollWidth > clientWidth + 1) overflows.push(`${name} @${width}: scrollWidth ${scrollWidth} > ${clientWidth}`)
      await page.screenshot({ path: `${SHOT_DIR}/layout-${name}-${width}.png` })
    }
  }
  expect(overflows, overflows.join('\n')).toEqual([])
})
