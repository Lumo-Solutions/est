import { expect, test, type Browser, type Page } from '@playwright/test'
import { DEMO_TOTP_SECRETS, generateTotp } from './totp'
import { readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// Fixture project app/cli.py::simulate_settlement builds/reuses (see
// global-setup.ts) -- one BOQ line with an ACCEPTED quotation line item
// from "D1 Simulation Vendor" (trade: Earthworks), no settlement built
// through the UI yet each time these specs run (SettlementPage.tsx's
// REBUILDABLE_STATUSES lets "Build new settlement draft" run again after
// the CLI's own simulation leaves the project's current settlement "won").
export const D1_SIM_PROJECT_CODE = 'D1-SIM'

interface ProjectSummary {
  id: string
  code: string
  name: string
}

// Real Keycloak login form (no mocked /auth/me) -- see
// docs/keycloak-setup.md's "Interactive browser login in dev" section.
// Real Keycloak login. With MFA on (the default), the browser-stepup flow's
// bronze level is password + TOTP, so this completes both steps using the
// dev-fixed secret bootstrap.sh seeded (totp.ts's DEMO_TOTP_SECRETS). With
// DEV_DISABLE_MFA=true (dev/test only -- `make dev-mfa-off`) the password
// step redirects straight back and no OTP form ever appears. Which of the
// two happened is returned (true = the OTP form was shown and completed) so
// a spec can assert Keycloak and the backend agree about the mode. A human
// wanting to test genuine QR-code enrolment instead runs
// deploy/keycloak/dev-reset-totp-user.sh first (see docs/keycloak-setup.md).
export async function loginViaKeycloak(page: Page, username: string, password: string): Promise<boolean> {
  await page.goto('/api/v1/auth/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
  const landed = page
    .waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
    .then(() => 'landed' as const)
    .catch(() => 'landed' as const)
  const otpShown = page
    .locator('#otp')
    .waitFor()
    .then(() => 'otp' as const)
    .catch(() => 'landed' as const)
  const otpPrompted = (await Promise.race([landed, otpShown])) === 'otp'
  if (otpPrompted) {
    const secret = DEMO_TOTP_SECRETS[username]
    if (!secret) throw new Error(`No dev-fixed TOTP secret known for '${username}' -- see totp.ts's DEMO_TOTP_SECRETS`)
    // Same form/button id ("kc-login") on the OTP step as the password step.
    await submitTotpCode(page, '#otp', () => page.locator('#kc-login').click(), secret)
  }
  // Keycloak redirects through /api/v1/auth/callback and lands back on the
  // SPA -- wait for that round trip instead of a fixed path, since `next`
  // can vary.
  await page.waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
  return otpPrompted
}

// True when the backend reports DEV_DISABLE_MFA is active (GET /auth/me ->
// mfa_disabled_dev; only ever true in dev/test). Needs a logged-in page.
export async function isMfaDisabledDev(page: Page): Promise<boolean> {
  const me = await page.request.get('/api/v1/auth/me')
  return ((await me.json()) as { mfa_disabled_dev?: boolean }).mfa_disabled_dev === true
}

// For specs whose whole point is a REAL Keycloak step-up: with MFA off there
// is nothing to prove, so skip -- loudly (console + skip reason in the
// report), never silently pass. Turn MFA on with `make dev-mfa-on`
// (deploy/keycloak/test-stepup-freshness.sh does it itself).
export async function skipLoudlyIfMfaDisabled(page: Page): Promise<void> {
  if (!(await isMfaDisabledDev(page))) return
  const reason = 'SKIPPED: DEV_DISABLE_MFA is on, so no real MFA step-up happens -- run `make dev-mfa-on` to run this test.'
  console.error(`
${'!'.repeat(78)}
!! ${reason}
${'!'.repeat(78)}
`)
  test.skip(true, reason)
}

// A code generated right before submission can still straddle Keycloak's
// 30s step boundary by the time the request is actually validated
// server-side (network + form-processing latency), occasionally (not
// deterministically) rejecting an otherwise-correct code with "Invalid
// authenticator code." -- confirmed by reproducing it directly against the
// real dev Keycloak (independently verified generateTotp() against a
// reference Python implementation first, to rule out a code bug).
//
// This does NOT retry immediately: Keycloak's brute-force protection
// (realm-installtec.json's bruteForceProtected) has a "quick login check"
// that penalizes repeated attempts within quickLoginCheckMilliSeconds
// (default 1000ms) with a ~60s forced wait (minimumQuickLoginWaitSeconds,
// default) REGARDLESS of whether the next code is correct -- retrying fast
// turns one boundary miss into a guaranteed failure. If the first attempt
// fails, this waits out that exact penalty window once before trying
// again with a freshly computed code; dev-reset-totp-user.sh also clears
// any brute-force history left over from a PREVIOUS run so this always
// starts from zero.
async function submitTotpCode(page: Page, fieldSelector: string, submit: () => Promise<void>, secret: string): Promise<void> {
  await waitForUnusedOtpStep(page, secret)
  await page.locator(fieldSelector).fill(await generateTotp(secret))
  await submit()
  if (!(await page.getByText('Invalid authenticator code.').isVisible().catch(() => false))) return
  await page.waitForTimeout(65_000)
  await waitForUnusedOtpStep(page, secret)
  await page.locator(fieldSelector).fill(await generateTotp(secret))
  await submit()
}

// ROOT CAUSE of the ~1-minute logins and intermittent "Invalid authenticator
// code" in back-to-back specs: the realm has otpPolicyCodeReusable=false, so
// Keycloak rejects a TOTP code from a 30s step this user has ALREADY logged
// in with. Two logins by the same user in the same step (a spec's login right
// after the previous spec's, or after that spec's own 65s retry) therefore
// fail the first attempt, and the retry's success lands late in a step that
// the next login shares -- so the failure cascaded through a whole run. The
// last step used per secret is kept in a temp file (shared across Playwright
// processes) and the next login waits for a strictly later step instead.
const OTP_STEP_MS = 30_000
const OTP_STATE_FILE = join(tmpdir(), 'installtec-e2e-last-otp-step.json')

function readOtpState(): Record<string, number> {
  try {
    return JSON.parse(readFileSync(OTP_STATE_FILE, 'utf-8')) as Record<string, number>
  } catch {
    return {}
  }
}

async function waitForUnusedOtpStep(page: Page, secret: string): Promise<void> {
  const state = readOtpState()
  const last = state[secret]
  if (last !== undefined && Math.floor(Date.now() / OTP_STEP_MS) <= last) {
    // +1.5s margin so the code is generated well inside the new step.
    await page.waitForTimeout((last + 1) * OTP_STEP_MS - Date.now() + 1_500)
  }
  state[secret] = Math.floor(Date.now() / OTP_STEP_MS)
  try {
    writeFileSync(OTP_STATE_FILE, JSON.stringify(state))
  } catch {
    // Best effort: without the file we are back to the old (retrying) behaviour.
  }
}

// lib/api.ts's ApiError.isStepUpRequired handling does a full
// `window.location.href = stepUpUrl()` on a 403 urn:installtec:step-up-required
// (app/core/errors.py::StepUpRequiredError, app/security/deps.py::require_mfa_step_up)
// -- this completes the resulting re-authentication and waits for the
// browser to land back on the original page.
//
// CORRECTED (fix/keycloak-step-up review item 3): an earlier version of
// this helper filled a `#password` field first, on the assumption that
// Keycloak's browser-stepup flow re-demanded the password too. Verified
// live against the real dev stack that this is wrong -- Cookie already
// reattached the existing bronze session, and Level 1's own
// conditional-level-of-authentication (deploy/keycloak/bootstrap.sh) is
// satisfied by that existing session well within its 28800s max-age, so a
// step-up request (acr_values=silver) skips Level 1 (password+OTP)
// entirely and goes straight to Level 2, which is OTP alone -- Keycloak's
// page shows only a read-only username and a one-time-code field, no
// password field at all. Filling one hung `.fill('#password')` forever
// (no such element ever appears), timing out the whole test rather than
// failing fast, since neither this config nor playwright.*.config.ts sets
// an explicit actionTimeout.
export async function completeMfaStepUp(page: Page, totpSecret: string): Promise<void> {
  const signIn = () => page.getByRole('button', { name: 'Sign In' }).click()
  await submitTotpCode(page, '#otp', signIn, totpSecret)
  await page.waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
}

// For a mutating page.request call: the double-submit CSRF cookie
// (security/csrf.py) isn't attached automatically the way the browser
// attaches it for the page's own fetch() calls, so this reads it back out
// of the same browsing context's cookie jar.
export async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies()
  const csrf = cookies.find((c) => c.name === '__Host-ins_csrf')
  if (!csrf) throw new Error('__Host-ins_csrf cookie not found -- not logged in?')
  return { 'X-CSRF-Token': csrf.value }
}

// None of the CLI's `simulate-*`/`seed-qa-demo-data` fixtures ever add a
// *real* Keycloak dev user (estimator1, lead1, ...) as a ProjectMember --
// they all use their own synthetic "_SIM_*"/"_E2E_*" user ids instead (see
// app/cli.py). app/services/projects.py::assert_can_see_project requires
// membership for estimator/lead_estimator specifically (bd_director,
// managing_director, and procurement_head all bypass it via
// _PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES) -- so an interactive-login
// lead1/estimator1 spec hits "Not a member of project ..." on its very
// first write against any fixture project, not because of a bug in the
// thing being tested. Confirmed live: docs/ui-qa/issues.md UI-P2-008. This
// adds `username` as a member of `projectId` (idempotent -- a second add is
// a harmless 204, add_member has no uniqueness constraint issue in
// practice for this dev-only use) using a `bd1` session, which bypasses
// membership entirely and can also call POST /projects/{id}/members.
export async function ensureProjectMember(
  browser: Browser,
  projectId: string,
  username: 'estimator1' | 'lead1',
): Promise<void> {
  const password = username === 'estimator1' ? 'Estimator1Pass!' : 'Lead1Pass!'
  const userPage = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage()
  await loginViaKeycloak(userPage, username, password)
  const me = (await (await userPage.request.get('/api/v1/auth/me')).json()) as { sub: string }
  await userPage.close()

  const bdPage = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage()
  await loginViaKeycloak(bdPage, 'bd1', 'Bd1Pass!')
  const response = await bdPage.request.post(`/api/v1/projects/${projectId}/members`, {
    headers: await csrfHeaders(bdPage),
    data: { user_id: me.sub, project_role: null },
  })
  await bdPage.close()
  // (project_id, user_id) is ProjectMember's composite primary key -- a
  // second add for a user already a member hits that constraint, which
  // app/core/errors.py's integrity_error_handler turns into a 409, not a
  // 500. Idempotent from the caller's point of view: already a member is
  // exactly the state this function is trying to ensure.
  if (!response.ok() && response.status() !== 409) {
    throw new Error(`Failed to add ${username} as a member of project ${projectId}: ${response.status()} ${await response.text()}`)
  }
}

// Looks the fixture project up by code through the real API (same session
// cookie the page already has) rather than hard-coding its id, which is a
// fresh UUID on every fresh Postgres volume.
export async function findProjectByCode(page: Page, code: string): Promise<ProjectSummary> {
  const response = await page.request.get('/api/v1/projects')
  if (!response.ok()) {
    throw new Error(`GET /api/v1/projects failed: ${response.status()} ${await response.text()}`)
  }
  const projects = (await response.json()) as ProjectSummary[]
  const project = projects.find((p) => p.code === code)
  if (!project) {
    throw new Error(`Project with code ${code} not found -- did global-setup's dev-simulate-settlement run?`)
  }
  return project
}

interface SettlementLine {
  id: string
  direct_unit_cost: number | null
}

interface SettlementSummary {
  id: string
  is_current: boolean
  lines: SettlementLine[]
}

// GET /projects/{id}/bid-settlements (list_settlements_endpoint) builds its
// response with plain `BidSettlementOut.model_validate(s)`, unlike GET
// /bid-settlements/{id} (get_settlement_endpoint), which goes through
// _to_out() to also populate `lines`/`trade_overrides` -- the list endpoint
// always returns `lines: []` (the schema's default), regardless of how
// many lines the settlement actually has. Fetches the id from the list
// endpoint, then the real per-settlement lines from the detail one.
async function getCurrentSettlementWithLines(page: Page, projectId: string): Promise<SettlementSummary> {
  const listResp = await page.request.get(`/api/v1/projects/${projectId}/bid-settlements`)
  const settlements = (await listResp.json()) as SettlementSummary[]
  const current = settlements.find((s) => s.is_current)
  if (!current) throw new Error(`No current settlement for project ${projectId}`)

  const detailResp = await page.request.get(`/api/v1/bid-settlements/${current.id}`)
  if (!detailResp.ok()) {
    throw new Error(`GET /bid-settlements/${current.id} failed: ${detailResp.status()} ${await detailResp.text()}`)
  }
  return (await detailResp.json()) as SettlementSummary
}

// Deterministically forces the CURRENT settlement's persisted defaults to
// zero, regardless of whatever an earlier run (this spec's own previous
// run, or `make dev-simulate-settlement`'s own set_defaults call) left
// them at -- submit_settlement() computes off these persisted fields, not
// the cockpit's live slider preview (SimulationSliders never calls
// useUpdateSettlementDefaults -- see features/settlement/api.ts), so
// there's no UI control for this. All-zero defaults make margin-on-sell
// exactly 0%, which is what pins this settlement's approval routing to
// managing_director every run (see settlement.spec.ts).
export async function forceZeroDefaults(page: Page, projectId: string): Promise<void> {
  const current = await getCurrentSettlementWithLines(page, projectId)

  const patch = await page.request.patch(`/api/v1/bid-settlements/${current.id}/defaults`, {
    headers: await csrfHeaders(page),
    data: { default_plant_pct: 0, default_overhead_pct: 0, default_volatility_pct: 0, default_markup_pct: 0 },
  })
  if (!patch.ok()) {
    throw new Error(`Failed to zero settlement defaults: ${patch.status()} ${await patch.text()}`)
  }
}

// D1-SIM (see D1_SIM_PROJECT_CODE) is a long-lived dev fixture other
// `make dev-simulate-*` targets have also seeded BOQ lines into over time
// (e.g. Module B/C's semantic-matching simulation) -- app/services/
// settlement.py::build_settlement_draft resolves cost from an accepted
// quote for EVERY project BOQ line with a quantity, not just the one this
// spec cares about, so a freshly built draft can carry other lines this
// spec has no accepted quote for. Real (not mocked) manual-cost-entry
// calls, exactly the "manual entry (who and why)" cost source
// docs/preconstruction-build-brief.md's Phase 1 describes, unblock submit
// without needing those other simulations' own fixtures touched.
export async function resolveUnresolvedLines(page: Page, projectId: string): Promise<void> {
  const current = await getCurrentSettlementWithLines(page, projectId)

  const headers = await csrfHeaders(page)
  for (const line of current.lines) {
    if (line.direct_unit_cost != null) continue
    const patch = await page.request.patch(`/api/v1/bid-settlements/${current.id}/lines/${line.id}`, {
      headers,
      data: { cost_source: 'manual', manual_unit_cost: '1.00', source_note: 'real-backend Playwright fixture resolution' },
    })
    if (!patch.ok()) {
      throw new Error(`Failed to resolve settlement line ${line.id}: ${patch.status()} ${await patch.text()}`)
    }
  }
}

// Same build -> force-zero-defaults -> resolve -> submit sequence
// settlement.spec.ts drives inline, factored out so
// step-up-freshness.spec.ts (fix/keycloak-step-up) can put a FRESH D1-SIM
// settlement into "pending approval" for each of its three scenarios
// without repeating it three times. `page` must already be a logged-in
// submitter (e.g. bd1) -- this does not log in itself, unlike loginViaKeycloak.
export async function submitSettlementForApproval(page: Page, projectId: string): Promise<void> {
  await page.goto(`/projects/${projectId}/settlement`)
  const buildButton = page.getByRole('button', { name: /^Build( new)? settlement draft$/ })
  const submitButton = page.getByRole('button', { name: 'Submit for approval' })
  // Wait for the page's data to land before deciding: isVisible() alone
  // returns immediately, so it raced the settlement fetch and skipped the
  // build click on an already-approved settlement (which has no Submit).
  await buildButton.or(submitButton).first().waitFor({ state: 'visible' })
  if (await buildButton.isVisible()) {
    await buildButton.click()
  }
  await submitButton.waitFor({ state: 'visible' })
  await forceZeroDefaults(page, projectId)
  await resolveUnresolvedLines(page, projectId)
  await page.reload()
  await page.getByRole('button', { name: 'Submit for approval' }).click()
  await page.getByRole('button', { name: 'Approve' }).waitFor({ state: 'visible' })
}

// Clicks the settlement page's Approve button and reports which of the two
// real outcomes lib/api.ts's isStepUpRequired handling actually produces:
// a full-page redirect to Keycloak (`window.location.href = stepUpUrl()` on
// a 403 urn:installtec:step-up-required -- "blocked") or the page updating
// in place to show the approved banner ("approved"). Never mocks the
// decision -- this is reading the real consequence of the real
// has_recent_step_up check (app/security/deps.py) on whatever session state
// `page` currently has.
export async function attemptApprove(page: Page): Promise<'blocked' | 'approved'> {
  await page.getByRole('button', { name: 'Approve' }).click()
  const [blocked, approved] = await Promise.all([
    page.waitForURL((url) => url.pathname.startsWith('/realms/'), { timeout: 15_000 }).then(
      () => true,
      () => false,
    ),
    // SettlementPage.tsx's Phase 4 restyle renders the status as a shared
    // Badge (docs/ui-design-system.md section 4.8), whose text is exactly
    // the status word with no surrounding " -- " literal.
    page
      .getByText('approved', { exact: true })
      .waitFor({ state: 'visible', timeout: 15_000 })
      .then(
        () => true,
        () => false,
      ),
  ])
  if (blocked) return 'blocked'
  if (approved) return 'approved'
  throw new Error('Approve click neither redirected to step-up nor showed the approved banner within 15s')
}

const REBUILDABLE_SETTLEMENT_STATUSES = new Set(['approved', 'rejected', 'won', 'lost'])

async function currentSettlementStatus(page: Page, projectId: string): Promise<string | null> {
  const rows = (await (await page.request.get(`/api/v1/projects/${projectId}/bid-settlements`)).json()) as {
    is_current: boolean
    status: string
  }[]
  return rows.find((s) => s.is_current)?.status ?? null
}

// Approves the project's SUBMITTED settlement as md1 (a different user from
// the bd1 submitter, so segregation of duties holds), completing a real MFA
// step-up when the backend demands one and going straight through when
// DEV_DISABLE_MFA is on.
async function approveSubmittedSettlement(browser: Browser, projectId: string): Promise<void> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  try {
    const page = await context.newPage()
    await loginViaKeycloak(page, 'md1', 'Md1Pass!')
    await page.goto(`/projects/${projectId}/settlement`)
    if ((await attemptApprove(page)) === 'blocked') {
      await completeMfaStepUp(page, DEMO_TOTP_SECRETS.md1)
      const second = await attemptApprove(page)
      if (second !== 'approved') throw new Error('settlement was still not approved after a real MFA step-up')
    }
  } finally {
    await context.close()
  }
}

// Puts the project's CURRENT settlement into a known lifecycle state through
// the real UI/API flow, so a spec never has to skip because an earlier spec
// (or `make dev-simulate-settlement`) left the shared D1-SIM fixture
// somewhere else. `page` must be a logged-in bd1 (or md1) page.
//   'draft'       -> a submittable draft (no outcome yet)
//   'approved'    -> approved, exportable
//   'rebuildable' -> any status the cockpit offers "Build new draft" from
export async function driveSettlementTo(
  page: Page,
  browser: Browser,
  projectId: string,
  target: 'draft' | 'approved' | 'rebuildable',
): Promise<void> {
  let status = await currentSettlementStatus(page, projectId)
  if (target === 'rebuildable' && status !== null && REBUILDABLE_SETTLEMENT_STATUSES.has(status)) return
  if (target === 'approved' && status === 'approved') return
  if (target === 'draft' && status === 'draft') return

  if (status === 'submitted') {
    await approveSubmittedSettlement(browser, projectId)
    status = await currentSettlementStatus(page, projectId)
    if (target === 'rebuildable' || target === 'approved') return
  }
  // From here the settlement is a draft, a rebuildable status, or absent:
  // submitSettlementForApproval builds a new draft first when it has to.
  if (target === 'draft') {
    if (status !== 'draft') {
      await page.goto(`/projects/${projectId}/settlement`)
      await page.getByRole('button', { name: /^Build( new)? settlement draft$/ }).click()
      // Role-agnostic wait (only bd/md can see "Submit for approval"): the
      // server reports the new draft as current.
      await expect.poll(() => currentSettlementStatus(page, projectId), { timeout: 30_000 }).toBe('draft')
    }
    return
  }
  await submitSettlementForApproval(page, projectId)
  await approveSubmittedSettlement(browser, projectId)
}
