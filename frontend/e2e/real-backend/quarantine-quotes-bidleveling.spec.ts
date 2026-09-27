import { expect, test } from '@playwright/test'
import { csrfHeaders, ensureProjectMember, findProjectByCode, loginViaKeycloak } from './helpers'

// D1-SIM and QA-DEMO have accumulated throwaway "Playwright package
// <timestamp>"/"QA-P2-pkg-<timestamp>" packages from earlier Phase 2 spec
// runs (ProcurementPackagesPage's own create-package tests) alongside their
// one real fixture package -- selecting by a hardcoded dropdown `index`
// grabs whichever junk package happens to sort first and has no RFQs/
// quotations at all. Selecting by the fixture's actual, known label is
// robust against that accumulation (and against more of it happening in
// the future).
const D1_SIM_PACKAGE_LABEL = 'D1 Simulation Package'
const QA_DEMO_PACKAGE_LABEL = 'QA Demo Package'

// Phase 2 UI QA (docs/ui-qa-brief.md) -- QuarantineQueuePage, QuoteReviewPage,
// BidLevelingPage. See docs/ui-qa/issues.md UI-P2-012 onwards for the full
// writeup of what each guards against.

test.describe('QuarantineQueuePage', () => {
  test('the review queue excludes ordinary auto-processed emails and only shows ones needing attention', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')

    // API-level, not UI-row-counting: precise and matches the exact
    // regression this guards (list_inbound_review_queue used to filter on
    // review_status alone, which is "open" for every inbound email --
    // including ones that were auto-processed and never needed review at
    // all). See UI-P2-012 / test_review_queue_excludes_auto_processed_
    // emails_that_never_needed_review (backend/tests/integration).
    const response = await page.request.get('/api/v1/quotation-inbound-review')
    expect(response.ok()).toBe(true)
    const queue = (await response.json()) as { id: string; needs_review: boolean }[]
    expect(queue.length).toBeGreaterThan(0)
    for (const row of queue) expect(row.needs_review).toBe(true)

    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/quarantine`)
    await expect(page.getByRole('heading', { name: 'Quarantine and review queue' })).toBeVisible()
    // Not "Nothing needs review" -- the demo tenant has real needs_review
    // rows (seeded by earlier make dev-simulate-* runs), so an empty state
    // here would itself indicate the fix regressed.
    await expect(page.getByText('Nothing needs review')).toHaveCount(0)
    await expect(page.locator('table tbody tr').first()).toBeVisible()
  })

  test('resolve-tenant is not offered to a non-platform_admin role', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/quarantine`)
    await expect(page.getByPlaceholder('Tenant ID')).toHaveCount(0)

    // No platform_admin demo user is seeded anywhere in this repo (checked
    // deploy/keycloak/bootstrap.sh's seed_user calls and every real-backend
    // spec) -- the "Resolve tenant" action, the only UI for that role's one
    // exclusive capability, cannot be exercised live at all in this dev
    // environment. Confirmed by absence, not by a failing login attempt.
    // See docs/ui-qa/issues.md.
  })
})

test.describe('QuoteReviewPage', () => {
  async function openQuoteReview(page: import('@playwright/test').Page, projectCode: string, packageLabel: string) {
    const project = await findProjectByCode(page, projectCode)
    await page.goto(`/projects/${project.id}/procurement/quotes`)
    const packageSelect = page.locator('select').first()
    await packageSelect.selectOption({ label: packageLabel })
    const rfqSelect = page.locator('select').nth(1)
    await rfqSelect.selectOption({ index: 1 })
    return project
  }

  test('estimator sees no review actions, and a direct accept attempt 403s server-side', async ({ page, browser }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    // estimator (unlike procurement_head/bd_director/managing_director) is
    // NOT in _PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES -- without this,
    // GET /projects/{id}/procurement-packages returns nothing for a
    // non-member estimator and the package dropdown never gets an option
    // to select at all (the pre-existing gap this repo's own
    // ensureProjectMember helper exists for -- see UI-P2-008).
    const projectForMembership = await findProjectByCode(page, 'QA-DEMO')
    await ensureProjectMember(browser, projectForMembership.id, 'estimator1')
    await openQuoteReview(page, 'QA-DEMO', QA_DEMO_PACKAGE_LABEL)

    // _REVIEW_ROLES (backend/app/api/v1/routes/quotation_ingestion.py) is
    // procurement_head/bd_director/managing_director only -- notably NOT
    // estimator or lead_estimator, even though this page is nav-gated to
    // "all". Before this fix, every one of these buttons was fully enabled
    // and silently 403'd. See UI-P2-013.
    await expect(page.getByRole('button', { name: 'Accept' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Reject', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Reject quotation' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Set currency (VAT-incl.)' })).toHaveCount(0)

    const quotationsResp = await page.request.get(`/api/v1/rfqs/${await rfqIdFromPage(page)}/quotations`)
    const quotations = (await quotationsResp.json()) as { id: string }[]
    expect(quotations.length).toBeGreaterThan(0)
    const lineItemsRes = await page.request.get(`/api/v1/quotations/${quotations[0].id}/line-items`)
    const lineItems = (await lineItemsRes.json()) as { id: string }[]
    expect(lineItems.length).toBeGreaterThan(0)

    const acceptResp = await page.request.post(`/api/v1/quotation-line-items/${lineItems[0].id}/accept`, {
      headers: await csrfHeaders(page),
    })
    expect(acceptResp.status()).toBe(403)
  })

  async function rfqIdFromPage(page: import('@playwright/test').Page): Promise<string> {
    const rfqSelect = page.locator('select').nth(1)
    return rfqSelect.inputValue()
  }

  test('procurement_head sees review actions and money fields render as real numbers (JsonDecimal fix)', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    // procurement_head bypasses the membership check entirely (see above),
    // so no ensureProjectMember call is needed here.
    await openQuoteReview(page, 'D1-SIM', D1_SIM_PACKAGE_LABEL)

    await expect(page.getByRole('button', { name: 'Accept' }).first()).toBeVisible()

    // Regression guard for UI-P2-011/UI-P2-012 (JsonDecimal sweep): before
    // that fix, QuotationLineItemOut.unit_price/quantity serialized to JSON
    // as a STRING ("45.5000"), which -- while React happily renders either
    // shape as text, so this alone wouldn't have caught a silent string --
    // is confirmed here at the API layer instead, which is the actual
    // contract the frontend types (frontend/src/types/api.ts: `number`)
    // depend on.
    const rfqId = await rfqIdFromPage(page)
    const quotationsResp = await page.request.get(`/api/v1/rfqs/${rfqId}/quotations`)
    const [quotation] = (await quotationsResp.json()) as { id: string; stated_total: unknown }[]
    const lineItemsRes = await page.request.get(`/api/v1/quotations/${quotation.id}/line-items`)
    const lineItems = (await lineItemsRes.json()) as { unit_price: unknown; quantity: unknown; confidence: unknown }[]
    expect(lineItems.length).toBeGreaterThan(0)
    for (const li of lineItems) {
      expect(typeof li.unit_price).toBe('number')
      expect(typeof li.quantity).toBe('number')
      expect(typeof li.confidence).toBe('number')
    }

    // And that it actually renders visibly as a plain number in the DOM,
    // not "[object Object]" or a quoted string.
    await expect(page.locator('table').first()).toContainText(/\d/)
  })
})

test.describe('BidLevelingPage', () => {
  test('procurement_head sees a populated matrix with numeric cell prices (JsonDecimal fix)', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, 'D1-SIM')
    await page.goto(`/projects/${project.id}/procurement/bid-leveling`)
    await page.locator('select').selectOption({ label: D1_SIM_PACKAGE_LABEL })

    const packageId = await page.locator('select').inputValue()
    const response = await page.request.get(`/api/v1/procurement-packages/${packageId}/bid-leveling`)
    expect(response.ok()).toBe(true)
    const rows = (await response.json()) as { cells: { unit_price: unknown; normalized_unit_price: unknown }[] }[]
    expect(rows.length).toBeGreaterThan(0)
    const cells = rows.flatMap((r) => r.cells)
    expect(cells.length).toBeGreaterThan(0)
    for (const cell of cells) {
      expect(typeof cell.unit_price).toBe('number')
      if (cell.normalized_unit_price !== null) expect(typeof cell.normalized_unit_price).toBe('number')
    }

    await expect(page.locator('table')).toBeVisible()
    await expect(page.locator('table tbody tr').first()).toBeVisible()
  })

  test('selecting a vendor cell shows its exclusion-flags panel without console errors', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })

    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, 'D1-SIM')
    await page.goto(`/projects/${project.id}/procurement/bid-leveling`)
    await page.locator('select').selectOption({ label: D1_SIM_PACKAGE_LABEL })
    await page.locator('table tbody tr').first().locator('button').first().click()

    await expect(page.getByRole('heading', { name: 'Exclusion flags and citations' })).toBeVisible()
    expect(errors).toEqual([])
  })
})
