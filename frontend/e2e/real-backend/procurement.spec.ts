import { expect, test } from '@playwright/test'
import { D1_SIM_PROJECT_CODE, findProjectByCode, loginViaKeycloak } from './helpers'

interface TaxonomyNode {
  id: string
  name: string
}

// Real backend, real Keycloak login, no page.route mocks. Reuses the
// D1-SIM fixture project (global-setup.ts runs `make dev-simulate-settlement`
// first) for its existing BOQ line and its "D1 Simulation Vendor", which is
// prequalified for the Earthworks trade -- see app/cli.py's
// _get_or_create_d1_demo_rfq. This spec creates its OWN package on that
// project so it doesn't depend on, or disturb, the settlement spec's use
// of the CLI's own "D1 Simulation Package".
//
// bd1 (bd_director), not lead1: app_can_see_project()'s RLS bypass
// (app/db/ddl.py) only covers managing_director/bd_director/procurement_head
// -- lead_estimator needs an explicit project_members row, which this
// project only has for the CLI simulation's own SYNTHETIC lead-estimator
// id (app/cli.py::simulate_settlement), not the real Keycloak "lead1"
// user. Using lead1 here 403s on package creation.
test('procurement: create a package and draft an RFQ to a matched vendor', async ({ page }) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

  const taxonomyResponse = await page.request.get('/api/v1/taxonomy')
  expect(taxonomyResponse.ok()).toBe(true)
  const taxonomy = (await taxonomyResponse.json()) as TaxonomyNode[]
  const earthworks = taxonomy.find((t) => t.name === 'Earthworks')
  if (!earthworks) throw new Error('Earthworks trade node not found -- did global-setup\'s dev-simulate-settlement run?')

  await page.goto(`/projects/${project.id}/procurement/packages`)

  const packageName = `Playwright package ${Date.now()}`
  await page.getByPlaceholder('Package name').fill(packageName)
  // Vendor matching (match_vendors) hard-requires a trade_node_id on the
  // package -- see app/services/procurement.py -- so this has to be set at
  // creation time, not left on "No trade".
  await page.getByRole('combobox').selectOption(earthworks.id)
  await page.getByRole('button', { name: 'Create package' }).click()

  const packageButton = page.getByRole('button', { name: new RegExp(`^${packageName} -- `) })
  await expect(packageButton).toBeVisible()
  await packageButton.click()

  // The D1-SIM project's one BOQ line ("Excavation to formation level")
  // isn't linked to this brand-new package yet, so it's available to add.
  // selectOption's {label} form needs an exact string, and the option's
  // full text is "<item_no>: Excavation to formation level", so read its
  // value attribute instead of guessing the item_no formatting.
  const boqOption = page.locator('select[multiple] option', { hasText: 'Excavation to formation level' })
  const boqItemId = await boqOption.getAttribute('value')
  if (!boqItemId) throw new Error('BOQ item option for "Excavation to formation level" not found')
  await page.locator('select[multiple]').selectOption(boqItemId)
  await page.getByRole('button', { name: 'Add items' }).click()
  await expect(page.getByText('Excavation to formation level')).toBeVisible()

  const vendorRow = page.locator('li', { hasText: 'D1 Simulation Vendor' })
  await expect(vendorRow).toBeVisible()
  await vendorRow.getByRole('checkbox').check()

  await page.getByRole('button', { name: 'Draft RFQs' }).click()

  await expect(page.getByRole('cell', { name: 'draft' })).toBeVisible()
})
