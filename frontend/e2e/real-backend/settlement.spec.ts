import { expect, test } from '@playwright/test'
import {
  completeMfaStepUp,
  D1_SIM_PROJECT_CODE,
  findProjectByCode,
  forceZeroDefaults,
  isMfaDisabledDev,
  loginViaKeycloak,
  resolveUnresolvedLines,
} from './helpers'
import { DEMO_TOTP_SECRETS } from './totp'

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
  // Wait for the page to settle on one of the two states first: a bare
  // isVisible() doesn't wait, so on a fast load (e.g. right after another
  // spec left a rejected settlement current) it skipped the build click.
  await expect(buildButton.or(page.getByRole('button', { name: 'Submit for approval' }))).toBeVisible()
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
  // actually routed to, and a dev-fixed TOTP secret seeded by
  // deploy/keycloak/bootstrap.sh (see totp.ts's DEMO_TOTP_SECRETS), same as
  // every other demo user. Approve 403s with urn:installtec:step-up-required
  // the first time (bd1's own submitter session is bronze-only, and so is
  // md1's fresh login -- see app/security/deps.py::has_recent_step_up),
  // which lib/api.ts turns into a full-page redirect through Keycloak's
  // real re-authentication: a genuine MFA step-up
  // (deploy/keycloak/realm-installtec.json's browser-stepup flow reattaches
  // md1's existing bronze session via the Cookie authenticator, so this is
  // just the incremental OTP step, not password again -- see
  // docs/build-log.md's fix/keycloak-step-up section), not a UI-level retry.
  const mdContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const mdPage = await mdContext.newPage()
  await loginViaKeycloak(mdPage, 'md1', 'Md1Pass!')
  await mdPage.goto(`/projects/${project.id}/settlement`)

  const approveButton = mdPage.getByRole('button', { name: 'Approve' })
  await expect(approveButton).toBeEnabled()
  await approveButton.click()
  // With DEV_DISABLE_MFA on (dev/test only) that first click already
  // approved -- there is no step-up to complete or retry.
  if (!(await isMfaDisabledDev(mdPage))) {
    await completeMfaStepUp(mdPage, DEMO_TOTP_SECRETS.md1)
    await approveButton.click()
  }
  // SettlementPage.tsx's Phase 4 restyle renders the status as a shared
  // Badge (docs/ui-design-system.md section 4.8) rather than plain
  // " -- approved -- " text, so the version number and the status badge are
  // asserted separately instead of as one literal string.
  await expect(mdPage.getByText(/^v\d+$/)).toBeVisible()
  await expect(mdPage.getByText('approved', { exact: true })).toBeVisible()
  await mdContext.close()
})
