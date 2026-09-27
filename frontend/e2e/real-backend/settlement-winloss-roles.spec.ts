import { expect, test } from '@playwright/test'
import {
  csrfHeaders,
  D1_SIM_PROJECT_CODE,
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

  const buildButton = page.getByRole('button', { name: /^Build( new)? settlement draft$/ })
  test.skip(
    !(await buildButton.isVisible().catch(() => false)),
    'D1-SIM is mid-lifecycle (draft/submitted, not a REBUILDABLE_STATUSES status) from another spec run -- ' +
      'the role gate is still enforced server-side regardless of this, but this specific test needs the button offered to bd1 to prove the *client* also hides it correctly for estimator1.',
  )

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
  await page.goto(`/projects/${project.id}/settlement`)

  // Reuses whatever "draft" D1-SIM is already sitting in (this fixture is
  // frequently left at "draft" by other runs -- see the non-idempotency
  // notes in docs/ui-qa/log.md) rather than requiring a REBUILDABLE_STATUSES
  // status like the build-gate test above; only skips if D1-SIM is neither
  // draft NOR buildable into one, which would mean it's already
  // submitted/decided and this button is correctly hidden for a different
  // (also correct) reason.
  const buildButton = page.getByRole('button', { name: /^Build( new)? settlement draft$/ })
  if (await buildButton.isVisible().catch(() => false)) await buildButton.click()
  const submitButton = page.getByRole('button', { name: 'Submit for approval' })
  test.skip(
    !(await submitButton.isVisible().catch(() => false)),
    'D1-SIM is not in "draft" and could not be built into one -- already submitted/decided from another run.',
  )

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

  const settlements = (await (await page.request.get(`/api/v1/projects/${project.id}/bid-settlements`)).json()) as {
    is_current: boolean
    outcome: string | null
  }[]
  const current = settlements.find((s) => s.is_current)
  test.skip(!current, 'No current settlement on D1-SIM yet -- global-setup should have built one via make dev-simulate-settlement')
  test.skip(
    current!.outcome != null,
    'D1-SIM already has a recorded outcome from another run -- both roles would see the same read-only view, which does not exercise this gate',
  )

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
}) => {
  // Phase 2 UI QA (docs/ui-qa/issues.md UI-P2-020): confirms downloadFile()
  // (frontend/src/lib/api.ts) actually gets a real Content-Disposition
  // filename from the server rather than falling back to its hardcoded
  // 'settlement.xlsx' -- and records the real (UUID-based, not
  // project-code-based) naming pattern live rather than only reading the
  // service code, so a future rename here shows up as a spec change here
  // too, not a surprise.
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

  // export_settlement (backend/app/services/settlement.py) correctly
  // refuses a non-approved settlement ("Bid settlement is draft, not
  // approved -- export is only available once approved") -- confirmed live
  // while writing this test, and ExportPage.tsx surfaces that error text
  // under the button rather than hiding the button, which is fine (the
  // button staying clickable and failing with a clear message is
  // acceptable UX for a genuinely conditional, not role-based, restriction
  // -- unlike the role-gate bugs elsewhere on this page's neighbors). Only
  // exercises the actual download when D1-SIM happens to be approved.
  const settlements = (await (await page.request.get(`/api/v1/projects/${project.id}/bid-settlements`)).json()) as {
    is_current: boolean
    status: string
  }[]
  const current = settlements.find((s) => s.is_current)
  test.skip(current?.status !== 'approved', `D1-SIM's current settlement is "${current?.status}", not "approved" -- export correctly refuses it.`)

  await page.goto(`/projects/${project.id}/export`)
  const downloadButton = page.getByRole('button', { name: 'Download generated .xlsx' })
  const [download] = await Promise.all([page.waitForEvent('download'), downloadButton.click()])
  expect(download.suggestedFilename()).toMatch(new RegExp(`^settlement-${project.id}-v\\d+\\.xlsx$`))
})
