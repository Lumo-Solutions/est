import type { Page } from '@playwright/test'
import { generateTotp } from './totp'

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
// Demo users are pre-provisioned by global-setup.ts (permanent password, no
// pending required actions), so this only exercises the username/password
// step, not TOTP enrolment -- that's a documented human first-login flow,
// not something most of these specs need to automate (see that doc for
// why). loginAndEnrollTotp below is the one exception, for a spec that
// specifically needs a real MFA step-up.
export async function loginViaKeycloak(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/api/v1/auth/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
  // Keycloak redirects through /api/v1/auth/callback and lands back on the
  // SPA -- wait for that round trip instead of a fixed path, since `next`
  // can vary.
  await page.waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
}

// Same login form, but for an account left with CONFIGURE_TOTP pending on
// purpose (dev-reset-totp-user.sh) so this can enrol a real TOTP
// credential itself and return its secret for a later real MFA step-up
// (completeMfaStepUp) -- see settlement.spec.ts.
export async function loginAndEnrollTotp(page: Page, username: string, password: string): Promise<string> {
  await page.goto('/api/v1/auth/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
  await page.waitForURL(/\/realms\/.*login-actions\/required-action/)
  const secret = await enrollTotp(page)
  await page.waitForURL((url) => !url.pathname.startsWith('/realms/') && !url.pathname.startsWith('/api/v1/auth/'))
  return secret
}

// Completes Keycloak's CONFIGURE_TOTP required-action page (reached right
// after loginViaKeycloak's password submit, for an account that still has
// that required action pending -- see dev-reset-totp-user.sh) the way a
// person would with an authenticator app: opens the "Unable to scan?"
// manual-entry view, reads the real human-readable secret out of
// #kc-totp-secret-key, and submits a freshly computed code. Returns the
// base32 secret so a later real MFA step-up (completeMfaStepUp) can
// generate a fresh code from the same now-registered credential --
// Keycloak never exposes a credential's secret again after enrolment, so
// this is the only time it's available.
export async function enrollTotp(page: Page): Promise<string> {
  await page.getByRole('link', { name: 'Unable to scan?' }).click()
  const secret = (await page.locator('#kc-totp-secret-key').innerText()).replace(/\s+/g, '')
  await submitTotpCode(page, '#totp', () => page.locator('#saveTOTPBtn').click(), secret)
  return secret
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
  await page.locator(fieldSelector).fill(generateTotp(secret))
  await submit()
  if (!(await page.getByText('Invalid authenticator code.').isVisible().catch(() => false))) return
  await page.waitForTimeout(65_000)
  await page.locator(fieldSelector).fill(generateTotp(secret))
  await submit()
}

// lib/api.ts's ApiError.isStepUpRequired handling does a full
// `window.location.href = stepUpUrl()` on a 403 urn:installtec:step-up-required
// (app/core/errors.py::StepUpRequiredError, app/security/deps.py::require_mfa_step_up)
// -- this completes the resulting re-authentication (acr_values=silver
// forces a real password + OTP challenge even with an existing SSO
// session, not just an OTP prompt) and waits for the browser to land back
// on the original page. The username field isn't present on this "please
// re-authenticate" page at all (Keycloak already knows who from the SSO
// session), so this only fills password + otp, unlike loginViaKeycloak.
export async function completeMfaStepUp(page: Page, password: string, totpSecret: string): Promise<void> {
  // The browser's URL stays on Keycloak's /protocol/openid-connect/auth
  // endpoint while it serves this form (the form's OWN action attribute
  // points at /login-actions/authenticate, which is where submitting it
  // goes, not where it's displayed) -- so this waits on the password
  // field itself rather than a URL, which Playwright's own action-waiting
  // on .fill() already does.
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
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
