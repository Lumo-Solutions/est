import { expect, test } from '@playwright/test'
import {
  attemptApprove,
  completeMfaStepUp,
  D1_SIM_PROJECT_CODE,
  findProjectByCode,
  loginViaKeycloak,
  skipLoudlyIfMfaDisabled,
  submitSettlementForApproval,
} from './helpers'
import { DEMO_TOTP_SECRETS } from './totp'

// fix/keycloak-step-up, review item 3: proves how Keycloak 26's auth_time
// actually behaves across a real step-up, against the real dev stack, not
// a unit-tested fabricated RequestContext (see
// backend/tests/unit/test_step_up.py for that half). Only meaningful when
// run via deploy/keycloak/test-stepup-freshness.sh, which lowers BOTH
// Keycloak's Level 2 loa-max-age and the backend's STEP_UP_MAX_AGE_S to the
// same short window (default 20s) first, and restores both afterwards --
// running this file directly against the real 300s default would need
// five-minute waits and prove nothing this doesn't. Real waits below, so
// this is slow and deliberately not part of settlement.spec.ts or the
// normal e2e:real-backend run.
const MAX_AGE_S = Number(process.env.STEP_UP_MAX_AGE_S ?? '20')
const PAST_MAX_AGE_MS = (MAX_AGE_S + 10) * 1000

test.setTimeout(600_000)

test('step-up freshness: auth_time behaviour across a real Keycloak step-up', async ({ page, browser }) => {
  await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
  await skipLoudlyIfMfaDisabled(page)
  const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)

  const mdContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const mdPage = await mdContext.newPage()

  // --- (a) a stale LOGIN-time auth_time must not block a step-up that just
  // happened -- the step-up itself has to refresh whatever signal
  // has_recent_step_up (app/security/deps.py) actually reads, or a real
  // user who took more than STEP_UP_MAX_AGE_S to get around to approving
  // something could never step up at all. ---
  await submitSettlementForApproval(page, project.id)
  await loginViaKeycloak(mdPage, 'md1', 'Md1Pass!')
  await mdPage.goto(`/projects/${project.id}/settlement`)
  await mdPage.waitForTimeout(PAST_MAX_AGE_MS) // let md1's LOGIN auth_time go stale before ever stepping up

  const bronzeAttempt = await attemptApprove(mdPage)
  expect(bronzeAttempt, 'bronze (no step-up yet) must always be blocked, stale or not').toBe('blocked')
  await completeMfaStepUp(mdPage, DEMO_TOTP_SECRETS.md1)

  const freshStepUpAttempt = await attemptApprove(mdPage)
  expect(
    freshStepUpAttempt,
    'a step-up that just happened must succeed even though the ORIGINAL login is long stale -- ' +
      'if this fails, has_recent_step_up is reading a signal Keycloak never refreshes on step-up ' +
      '(see docs/build-log.md for which one Keycloak 26 actually updates)',
  ).toBe('approved')

  // --- (b) the freshness just established above must itself expire --
  // silver from a step-up that is now old cannot go on approving forever,
  // or STEP_UP_MAX_AGE_S/loa-max-age would be dead configuration. ---
  await submitSettlementForApproval(page, project.id)
  await mdPage.reload()
  await mdPage.waitForTimeout(PAST_MAX_AGE_MS) // let the step-up from (a) go stale in turn

  const staleSilverAttempt = await attemptApprove(mdPage)
  expect(
    staleSilverAttempt,
    'a step-up older than STEP_UP_MAX_AGE_S must be treated as stale, not still-valid silver',
  ).toBe('blocked')

  // --- (c) from that same blocked state, a plain SSO re-authorize (our own
  // /auth/login, no acr_values -- the browser's existing Keycloak session
  // cookie lets the Cookie authenticator reattach silently, no form shown
  // at all) must not mint a token the backend accepts as fresh silver, no
  // matter what acr Keycloak's session-reattach labels the result. ---
  await mdPage.goto('/api/v1/auth/login')
  await mdPage.waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
  await mdPage.goto(`/projects/${project.id}/settlement`)

  const silentReauthAttempt = await attemptApprove(mdPage)
  expect(
    silentReauthAttempt,
    'a silent SSO re-authorize (cookie only, no OTP) must not be accepted as a fresh step-up',
  ).toBe('blocked')

  // Leaves D1-SIM rebuildable for other specs (SettlementPage.tsx's
  // REBUILDABLE_STATUSES needs 'approved'/'rejected'/'won'/'lost', not a
  // settlement stuck "pending approval" forever) -- a real, correctly fresh
  // step-up here also doubles as final confirmation that a legitimate
  // step-up still works after all of the above.
  await completeMfaStepUp(mdPage, DEMO_TOTP_SECRETS.md1)
  const cleanupAttempt = await attemptApprove(mdPage)
  expect(cleanupAttempt).toBe('approved')

  await mdContext.close()
})
