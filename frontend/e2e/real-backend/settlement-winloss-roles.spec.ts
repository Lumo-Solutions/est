import { expect, test } from '@playwright/test'
import {
  csrfHeaders,
  D1_SIM_PROJECT_CODE,
  driveSettlementTo,
  ensureProjectMember,
  findProjectByCode,
  loginViaKeycloak,
} from './helpers'

// Phase 2 UI QA (docs/ui-qa/issues.md UI-P2-018/019): SettlementPage's
// "Build (new) settlement draft" and "Submit for approval" buttons, and
// WinLossPage's record-outcome form, had no client-side role gate at all --
// the same recurring pattern already fixed on Typology/ProcurementPackages/
// QuoteReviewPage. The server was never at risk (require_roles/_OUTCOME_ROLES
// always enforced this), but an unauthorized role saw fully-enabled,
// working-looking controls that just silently 403'd.

test('settlement: build-draft button is role-gated client-side, and the server independently refuses a direct attempt', async ({
  page,
  browser,
}) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
  await page.goto(`/projects/${project.id}/settlement`)

  // Never skipped for fixture state: put the settlement into a status the
  // cockpit offers "Build new draft" from, whatever a previous run left.
  await driveSettlementTo(page, browser, project.id, 'rebuildable')
  await page.goto(`/projects/${project.id}/settlement`)
  await expect(page.getByRole('button', { name: /^Build( new)? settlement draft$/ })).toBeVisible()

  // estimator1 is not in BUILD_DRAFT_ROLES (lead_estimator/procurement_head/
  // bd_director/managing_director only, mirroring backend's _HEADER_ROLES).
  await ensureProjectMember(browser, project.id, 'estimator1')
  const estContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const estPage = await estContext.newPage()
  await loginViaKeycloak(estPage, 'estimator1', 'Estimator1Pass!')
  await estPage.goto(`/projects/${project.id}/settlement`)
  await expect(estPage.getByRole('button', { name: /^Build( new)? settlement draft$/ })).not.toBeVisible()

  const directAttempt = await estPage.request.post(`/api/v1/projects/${project.id}/bid-settlements`, {
    headers: await csrfHeaders(estPage),
  })
  expect(directAttempt.status()).toBe(403)
  await estContext.close()
})

test('settlement: submit-for-approval button is role-gated client-side to bd_director/managing_director', async ({
  page,
  browser,
}) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
  // Never skipped for fixture state: guarantee a submittable draft.
  await driveSettlementTo(page, browser, project.id, 'draft')
  await page.goto(`/projects/${project.id}/settlement`)
  await expect(page.getByRole('button', { name: 'Submit for approval' })).toBeVisible()

  // estimator1 has read/simulate access to this page (_LINE_ROLES) but is
  // not in _SUBMIT_ROLES (bd_director/managing_director only).
  await ensureProjectMember(browser, project.id, 'estimator1')
  const estContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const estPage = await estContext.newPage()
  await loginViaKeycloak(estPage, 'estimator1', 'Estimator1Pass!')
  await estPage.goto(`/projects/${project.id}/settlement`)
  await expect(estPage.getByRole('button', { name: 'Submit for approval' })).not.toBeVisible()
  await estContext.close()
})

test('win-loss: the record-outcome form is role-gated client-side; an unauthorized role sees a message instead', async ({
  page,
  browser,
}) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

  // A fresh draft has no recorded outcome, so both roles below see the
  // form-vs-message split this test is about, whatever a previous run left.
  await driveSettlementTo(page, browser, project.id, 'draft')

  // bd1 is in RECORD_OUTCOME_ROLES (mirrors backend's _OUTCOME_ROLES) --
  // sees the actual form.
  await page.goto(`/projects/${project.id}/win-loss`)
  await expect(page.getByRole('button', { name: 'Record outcome' })).toBeVisible()

  // lead_estimator is not -- sees the explanatory message, not the form.
  await ensureProjectMember(browser, project.id, 'lead1')
  const leadContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const leadPage = await leadContext.newPage()
  await loginViaKeycloak(leadPage, 'lead1', 'Lead1Pass!')
  await leadPage.goto(`/projects/${project.id}/win-loss`)
  await expect(leadPage.getByText(/Only bd_director\/managing_director can record it/)).toBeVisible()
  await expect(leadPage.getByRole('button', { name: 'Record outcome' })).not.toBeVisible()
  await leadContext.close()
})

test('export: downloading the generated workbook produces a real file with a working (if not very human-readable) name', async ({
  page,
  browser,
}) => {
  // Phase 2 UI QA (docs/ui-qa/issues.md UI-P2-020): confirms downloadFile()
  // (frontend/src/lib/api.ts) actually gets a real Content-Disposition
  // filename from the server rather than falling back to its hardcoded
  // 'settlement.xlsx' -- and records the real naming pattern live rather
  // than only reading the service code, so a future rename here shows up
  // as a spec change here too, not a surprise. Project-code-based (not
  // UUID-based) since the finish-brief follow-up's "export filenames use
  // the project code" fix (_project_code_for_filename, backend/app/
  // services/settlement.py) -- this assertion was updated to match live
  // when that fix's own e2e run caught this spec still asserting the old
  // UUID pattern.
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

  // export_settlement (backend/app/services/settlement.py) correctly
  // refuses a non-approved settlement ("Bid settlement is draft, not
  // approved -- export is only available once approved") -- confirmed live
  // while writing this test, and ExportPage.tsx surfaces that error text
  // under the button rather than hiding the button, which is fine (the
  // button staying clickable and failing with a clear message is
  // acceptable UX for a genuinely conditional, not role-based, restriction
  // -- unlike the role-gate bugs elsewhere on this page's neighbors).
  // drives D1-SIM to approved first (driveSettlementTo) so this never skips.
  await driveSettlementTo(page, browser, project.id, 'approved')

  await page.goto(`/projects/${project.id}/export`)
  const downloadButton = page.getByRole('button', { name: 'Download generated .xlsx' })
  const [download] = await Promise.all([page.waitForEvent('download'), downloadButton.click()])
  expect(download.suggestedFilename()).toMatch(new RegExp(`^settlement-${D1_SIM_PROJECT_CODE}-v\\d+\\.xlsx$`))
})
