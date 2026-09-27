import { expect, test } from '@playwright/test'
import {
  completeMfaStepUp,
  D1_SIM_PROJECT_CODE,
  findProjectByCode,
  forceZeroDefaults,
  loginAndEnrollTotp,
  loginViaKeycloak,
  resolveUnresolvedLines,
} from './helpers'

// Real backend, real Keycloak logins, no page.route mocks anywhere.
// global-setup.ts runs `make dev-simulate-settlement` first, which
// idempotently builds/reuses the D1-SIM project with a BOQ line already
// resolved from an ACCEPTED quotation line item -- this drives the
// settlement-specific slice of the UI (build/simulate/submit/approve) on
// top of that fixture, not the takeoff/BOQ-import pipeline that produced
// it (out of scope here).
test('settlement: build -> simulate -> submit -> approve as a different user', async ({ page, browser }) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
  await page.goto(`/projects/${project.id}/settlement`)

  // SettlementPage.tsx's REBUILDABLE_STATUSES lets this run again even
  // after a previous run (or the CLI simulation) left an approved/won
  // settlement current -- the button label differs only in that case. If
  // `make dev-simulate-settlement` itself got only as far as building a
  // draft before failing on unrelated stray BOQ lines (see
  // resolveUnresolvedLines's comment), that draft is reused as-is instead
  // -- rebuilding over an existing draft isn't offered by the UI, on
  // purpose (see build_settlement_draft's docstring).
  const buildButton = page.getByRole('button', { name: /^Build( new)? settlement draft$/ })
  if (await buildButton.isVisible().catch(() => false)) {
    await buildButton.click()
  }
  await expect(page.getByRole('button', { name: 'Submit for approval' })).toBeVisible()

  // Force deterministic, all-zero percentages regardless of whatever
  // either path above left the settlement's PERSISTED defaults at --
  // submit_settlement() computes off those, not the cockpit's live
  // slider preview (see forceZeroDefaults's comment) -- so margin-on-sell
  // is always exactly 0%, pinning this request's routing to
  // managing_director regardless of the BOQ fixture's actual amount.
  await forceZeroDefaults(page, project.id)
  await resolveUnresolvedLines(page, project.id)
  await page.reload()

  await expect(page.getByText('Requires approval by: managing_director')).toBeVisible()
  await expect(page.getByText('Margin on sell: 0.000%')).toBeVisible()

  await page.getByRole('button', { name: 'Submit for approval' }).click()

  // bd1 is the submitter -- segregation of duties disables their own
  // Approve/Reject (app/services/approvals.py::decide) and the UI reflects
  // it rather than letting the click fail server-side.
  await expect(page.getByText('Awaiting a different approver (SoD)')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()
  // Same 0.000% already confirmed pre-submit (line above) -- the approval
  // screen's own margin display (SubmitApprove) now shows it too, but the
  // cockpit's live simulation panel underneath still renders its own copy
  // of the same text, so asserting it again here would be a strict-mode
  // ambiguity, not a real check of anything new.

  // A different real user, in a separate browser context (separate
  // session cookie) -- md1 has the managing_director role this request
  // actually routed to. md1 is left with CONFIGURE_TOTP pending on purpose
  // (dev-reset-totp-user.sh, via global-setup.ts) so it enrols a REAL TOTP
  // credential here, because deciding an approval requires a real MFA
  // step-up (app/security/deps.py::require_mfa_step_up, acr=silver) --
  // Approve 403s with urn:installtec:step-up-required the first time,
  // which lib/api.ts turns into a full-page redirect through Keycloak's
  // re-authentication (password + a fresh OTP code from that same
  // credential), not just a UI-level retry.
  const mdContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const mdPage = await mdContext.newPage()
  const totpSecret = await loginAndEnrollTotp(mdPage, 'md1', 'Md1Pass!')
  await mdPage.goto(`/projects/${project.id}/settlement`)

  const approveButton = mdPage.getByRole('button', { name: 'Approve' })
  await expect(approveButton).toBeEnabled()
  await approveButton.click()
  await completeMfaStepUp(mdPage, 'Md1Pass!', totpSecret)

  // KNOWN PRE-EXISTING GAP (docs/build-log.md's Phase 10 section, fix
  // tracked on branch fix/keycloak-step-up): completing this real
  // Keycloak re-authentication, TOTP and all, still comes back acr=bronze,
  // not silver -- the realm import defines an acr.loa.map but never binds
  // an authentication flow that actually grants level 2 for completing
  // OTP, so require_mfa_step_up's `ctx.acr < silver` check can never be
  // satisfied by ANY real login today, and decide() 403s again exactly
  // the same way. This asserts that re-demand (the gate correctly firing
  // and re-firing) rather than claiming an approval that cannot actually
  // complete against the current realm config.
  await mdPage.goto(`/projects/${project.id}/settlement`)
  await expect(approveButton).toBeEnabled()
  await Promise.all([mdPage.waitForURL(/acr_values=silver/), approveButton.click()])
  await mdContext.close()
})
