import { expect, test } from '@playwright/test'
import { csrfHeaders, ensureProjectMember, findProjectByCode, loginViaKeycloak } from './helpers'

// Phase 2 UI QA (docs/ui-qa-brief.md) -- TypologyPage, BoqImportWizardPage,
// BoqReconciliationPage, ProcurementPackagesPage. See docs/ui-qa/issues.md
// UI-P2-007 through UI-P2-010 for the full writeup of what each guards
// against.

test.describe('TypologyPage', () => {
  test('estimator does not see Detect clusters, and a direct detect attempt 403s server-side', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/typology`)
    await expect(page.getByRole('heading', { name: 'Typology cluster review' })).toBeVisible()

    // Regression guard: detect/confirm/reject are lead_estimator/
    // procurement_head/managing_director only server-side (_STRUCTURE_ROLES
    // in backend/app/api/v1/routes/typology.py -- notably NOT estimator or
    // bd_director), but this page is nav-gated to "all" and had no
    // client-side role check at all, so an estimator saw a fully enabled
    // "Detect clusters" button that just failed silently (detect.isError was
    // never rendered either -- fixed alongside this gate).
    await expect(page.getByRole('button', { name: 'Detect clusters' })).toHaveCount(0)

    const response = await page.request.post(`/api/v1/projects/${project.id}/typology-clusters/detect`, {
      headers: await csrfHeaders(page),
    })
    expect(response.status()).toBe(403)
  })

  test('lead_estimator sees Detect clusters', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/typology`)
    await expect(page.getByRole('button', { name: 'Detect clusters' })).toBeVisible()
  })
})

test.describe('BoqImportWizardPage', () => {
  test('an unsupported file surfaces a clear server error on preview', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/boq/import`)

    await page.locator('#boq-file').setInputFiles({
      name: 'not-a-boq.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('this is not an excel or csv file'),
    })
    await page.locator('#item_no_column').fill('A')
    await page.locator('#description_column').fill('B')
    await page.getByRole('button', { name: 'Preview' }).click()

    // Whatever the exact backend message is, it must show up as text, not a
    // silently-stuck button or a blank page -- preview.isError is already
    // wired up, this just proves the whole path (bad file -> server 4xx ->
    // visible message) actually works end to end. role="alert" (not a
    // hardcoded color class, which Phase 4's design-token restyle changed
    // from text-red-600 to text-danger -- same color, different class name)
    // is the stable, semantic way to find it.
    await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 10_000 })
  })
})

test.describe('BoqReconciliationPage', () => {
  test('there is still no way to delete a BOQ item from the UI (known gap, Phase 3)', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/boq`)
    await expect(page.getByRole('heading', { name: 'BOQ reconciliation' })).toBeVisible()

    // DELETE /boq-items/{id} exists server-side (lead/proc/md) but nothing in
    // this page calls it -- see docs/ui-qa/coverage.md and issues.md
    // UI-P2-009. This test documents the gap so Phase 3 building the UI is a
    // deliberate change to a known assertion, not a silent regression either
    // way.
    await expect(page.getByRole('button', { name: /delete/i })).toHaveCount(0)
  })
})

test.describe('ProcurementPackagesPage', () => {
  test('estimator does not see the create-package form, and a direct create attempt 403s server-side', async ({
    page,
  }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/packages`)
    await expect(page.getByRole('heading', { name: 'Procurement packages and RFQs' })).toBeVisible()

    // Regression guard: this form had no hasRole gate at all -- an estimator
    // could fill it in and submit, hitting a 403 that produced literally no
    // feedback (createPackage.isError was never rendered either).
    await expect(page.getByPlaceholder('Package name')).toHaveCount(0)

    const response = await page.request.post(`/api/v1/projects/${project.id}/procurement-packages`, {
      headers: await csrfHeaders(page),
      data: { name: 'QA-P2-should-fail', trade_node_id: null },
    })
    expect(response.status()).toBe(403)
  })

  test('lead_estimator sees the create-package form with readable trade names, and creating one succeeds', async ({
    page,
    browser,
  }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    // None of the CLI's seed fixtures add lead1 (a real Keycloak dev user) as
    // a ProjectMember on any project -- see ensureProjectMember's own
    // comment and docs/ui-qa/issues.md UI-P2-008. Without this, "Create
    // package" 403s with "Not a member of project ..." regardless of the
    // fixes under test here.
    await ensureProjectMember(browser, project.id, 'lead1')
    await page.goto(`/projects/${project.id}/procurement/packages`)

    const nameInput = page.getByPlaceholder('Package name')
    await expect(nameInput).toBeVisible()

    // Regression guard: the trade dropdown rendered TradeNodeOut.path (a
    // Postgres ltree built from node ids for hierarchical queries, e.g.
    // "n073ec3ef_6b2f_4337_..."), not TradeNodeOut.name -- meaningless to a
    // real user. Assert every option is either the placeholder or a plain
    // name with no ltree-style id segments (no long hex/underscore runs).
    const optionTexts = await page.locator('select').nth(0).locator('option').allTextContents()
    expect(optionTexts.length).toBeGreaterThan(1)
    for (const text of optionTexts) {
      expect(text).not.toMatch(/^n[0-9a-f]{8}_/)
    }

    const uniqueName = `QA-P2-pkg-${Date.now()}`
    await nameInput.fill(uniqueName)
    await page.getByRole('button', { name: 'Create package' }).click()
    await expect(page.getByRole('button', { name: new RegExp(`^${uniqueName} --`) })).toBeVisible({ timeout: 10_000 })
  })
})
