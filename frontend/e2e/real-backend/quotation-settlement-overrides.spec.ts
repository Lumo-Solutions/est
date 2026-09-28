import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { csrfHeaders, D1_SIM_PROJECT_CODE, ensureProjectMember, findProjectByCode, loginViaKeycloak } from './helpers'

// Phase 3 gap-fill (docs/ui-qa-brief.md): quotation attachments viewer,
// exclusion-flag acknowledge, quotation/line fx-rate override, and
// settlement per-trade/per-line overrides. See docs/ui-qa/log.md's Phase 3
// section for the full writeup.

const D1_SIM_PACKAGE_LABEL = 'D1 Simulation Package'

test.describe('QuoteReviewPage: attachments and fx-rate', () => {
  test('procurement_head can toggle the attachments viewer and set a quotation fx-rate', async ({ page }) => {
    // procurement_head (unlike estimator/lead_estimator) is in
    // _PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES -- no ensureProjectMember
    // call needed (and calling it with a role outside its own
    // 'estimator1' | 'lead1' type would use the wrong hardcoded password
    // for that account, which is exactly what happened here on the first
    // attempt: real login failures against Keycloak's own brute-force
    // throttling, not a flaky test).
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

    await page.goto(`/projects/${project.id}/procurement/quotes`)
    await page.locator('select').first().selectOption({ label: D1_SIM_PACKAGE_LABEL })
    await page.locator('select').nth(1).selectOption({ index: 1 })

    const showAttachments = page.getByRole('button', { name: 'Show attachments' }).first()
    await expect(showAttachments).toBeVisible()
    await showAttachments.click()
    // Whether D1-SIM's fixture quotation actually has attachments varies by
    // run history -- either "No attachments." or a real list rendering
    // without error both prove the viewer works; only a thrown/error state
    // would be a real failure, and isError would render red text instead.
    await expect(page.getByText(/No attachments\.|KB/).first()).toBeVisible()

    // QuoteReviewPage.tsx's FX input placeholder is dynamic: "FX rate to
    // base" when quotation.fx_rate_to_base is unset, or "Current: <value>"
    // once a rate has already been recorded -- matching only /FX rate/
    // (as this test originally did) breaks the moment any prior run
    // (including this same test, re-run) has already set one, which is
    // exactly what happened here: a real test-authoring bug, not a product
    // bug or flakiness. Match both states.
    const fxInput = page.getByPlaceholder(/FX rate|Current:/).first()
    await expect(fxInput).toBeVisible()
    await fxInput.fill('3.6725')
    await page.getByRole('button', { name: 'Set FX rate' }).first().click()
    await expect(page.getByText(/Requires one of roles|500/).first()).toHaveCount(0)
  })

  test('estimator sees no fx-rate control, and a direct PATCH fx-rate 403s server-side', async ({ page, browser }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await ensureProjectMember(browser, project.id, 'estimator1')

    await page.goto(`/projects/${project.id}/procurement/quotes`)
    await page.locator('select').first().selectOption({ label: D1_SIM_PACKAGE_LABEL })
    await page.locator('select').nth(1).selectOption({ index: 1 })
    await expect(page.getByPlaceholder(/FX rate/)).toHaveCount(0)

    const quotesResp = await page.request.get(`/api/v1/rfqs/${await firstRfqId(page, project.id)}/quotations`)
    const quotations = (await quotesResp.json()) as { id: string }[]
    test.skip(quotations.length === 0, 'No quotations on this run\'s D1-SIM fixture')
    const resp = await page.request.patch(`/api/v1/quotations/${quotations[0].id}/fx-rate`, {
      headers: await csrfHeaders(page),
      data: { fx_rate_to_base: 3.5, fx_rate_date: '2026-01-01' },
    })
    expect(resp.status()).toBe(403)
  })
})

async function firstRfqId(page: import('@playwright/test').Page, projectId: string): Promise<string> {
  const packagesResp = await page.request.get(`/api/v1/projects/${projectId}/procurement-packages`)
  const packages = (await packagesResp.json()) as { id: string; name: string }[]
  const pkg = packages.find((p) => p.name === D1_SIM_PACKAGE_LABEL) ?? packages[0]
  const rfqsResp = await page.request.get(`/api/v1/procurement-packages/${pkg.id}/rfqs`)
  const rfqs = (await rfqsResp.json()) as { id: string }[]
  return rfqs[0]?.id ?? ''
}

test.describe('SettlementPage: per-trade and per-line overrides', () => {
  test('lead_estimator sees and can use the trade-override and line-override panels', async ({ page, browser }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await ensureProjectMember(browser, project.id, 'lead1')

    const settlementsResp = await page.request.get(`/api/v1/projects/${project.id}/bid-settlements`)
    const settlements = (await settlementsResp.json()) as { id: string; is_current: boolean }[]
    const current = settlements.find((s) => s.is_current)
    test.skip(!current, 'D1-SIM has no current settlement this run')
    if (!current) return

    await page.goto(`/projects/${project.id}/settlement`)
    await expect(page.getByRole('heading', { name: 'Settlement cockpit' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Per-trade overrides' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Per-line overrides' })).toBeVisible()

    // exact: true -- getByRole's default substring match also matches the
    // trade-override panel's "Set override" submit button, which (unlike
    // the line-override toggle) starts out disabled with no trade
    // selected, causing an indefinite click timeout on the wrong element.
    const overrideButtons = page.getByRole('button', { name: 'Override', exact: true })
    const count = await overrideButtons.count()
    test.skip(count === 0, 'D1-SIM has no settlement lines this run')
    if (count === 0) return

    await overrideButtons.first().click()
    const manualCostInput = page.getByLabel('Manual unit cost').first()
    await manualCostInput.fill('42.50')
    await page.getByRole('button', { name: 'Set cost' }).first().click()
    await expect(page.getByText('Requires one of roles')).toHaveCount(0)
  })

  test('estimator sees line overrides but not trade overrides; a direct PUT trade-override 403s server-side', async ({ page, browser }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await ensureProjectMember(browser, project.id, 'estimator1')

    const settlementsResp = await page.request.get(`/api/v1/projects/${project.id}/bid-settlements`)
    const settlements = (await settlementsResp.json()) as { id: string; is_current: boolean }[]
    const current = settlements.find((s) => s.is_current)
    test.skip(!current, 'D1-SIM has no current settlement this run')
    if (!current) return

    await page.goto(`/projects/${project.id}/settlement`)
    // estimator has real _LINE_ROLES access (line overrides), but not
    // _HEADER_ROLES (trade overrides) -- see UI-P2-023's finding that
    // estimator's real settlement permissions are broader than the nav
    // gate used to imply.
    await expect(page.getByRole('heading', { name: 'Per-trade overrides' })).toHaveCount(0)

    const resp = await page.request.put(`/api/v1/bid-settlements/${current.id}/trade-overrides/${randomUUID()}`, {
      headers: await csrfHeaders(page),
      data: { plant_pct: 5 },
    })
    expect(resp.status()).toBe(403)
  })
})
