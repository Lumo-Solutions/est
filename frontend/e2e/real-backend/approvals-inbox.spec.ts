import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import {
  attemptApprove,
  completeMfaStepUp,
  csrfHeaders,
  D1_SIM_PROJECT_CODE,
  driveSettlementTo,
  findProjectByCode,
  loginViaKeycloak,
  submitSettlementForApproval,
  useApprovalCleanup,
} from './helpers'
import { DEMO_TOTP_SECRETS } from './totp'

// fix/approvals-inbox: the "Approvals waiting for me" tile used to be plain
// text with nowhere to go. Real backend, real Keycloak, no mocks.

const APPROVALS_TILE = /Approvals waiting for me/

// Every request this file leaves pending (a failed run, the submitter's own request) is withdrawn when the file is done.
useApprovalCleanup(test)

function tileOf(page: Page) {
  return page.getByRole('heading', { name: APPROVALS_TILE }).locator('..')
}

// The number in the tile heading, "Approvals waiting for me (N)". The tile lists only the newest few rows, so the specs
// count with this and find a request on /approvals (the whole queue), never by its row in the tile.
async function tileCount(page: Page): Promise<number> {
  await page.goto('/dashboard')
  const heading = page.getByRole('heading', { name: APPROVALS_TILE })
  await expect(heading).toContainText(/\(\d+\)/)
  return Number(/\((\d+)\)/.exec(await heading.innerText())![1])
}

async function expectTileCount(page: Page, n: number): Promise<void> {
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: APPROVALS_TILE })).toContainText(`(${n})`)
}

async function login(browser: Browser, username: string, password: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await loginViaKeycloak(page, username, password)
  return page
}

// cost_rate_change has no producer in the app today (recording a rate applies
// immediately), so requests are created through the generic POST /approvals
// -- the same call a future producer would make. A unique amount (cents)
// identifies this run's request among any left over from earlier runs.
async function createCostRateRequest(page: Page, amount: string): Promise<string> {
  const response = await page.request.post('/api/v1/approvals', {
    headers: await csrfHeaders(page),
    data: {
      entity_type: 'cost_rate_change',
      entity_id: crypto.randomUUID(),
      amount,
      currency: 'AED',
      payload_snapshot: { reason: 'e2e cost rate change' },
    },
  })
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { id: string }).id
}

function uniqueAmount(): { raw: string; shown: string } {
  const cents = String(10 + Math.floor(Math.random() * 89)).padStart(2, '0')
  const suffix = String(Date.now() % 1000).padStart(3, '0')
  // Stays inside the lead_estimator tier (< 50,000).
  return { raw: `1${suffix}.${cents}`, shown: `AED 1,${suffix}.${cents}` }
}

// Runs `act` (a click that submits a decision). It either completes
// (MFA off, or the session is fresh) or the API answers step-up-required and
// lib/api.ts redirects to Keycloak; in that case do the real OTP step and
// run `act` once more, which the caller's `done` locator then confirms.
async function decideWithStepUp(
  page: Page,
  act: () => Promise<void>,
  done: () => Promise<unknown>,
  secretKey: keyof typeof DEMO_TOTP_SECRETS,
): Promise<void> {
  await act()
  const outcome = await Promise.race([
    page.waitForURL((url) => url.pathname.startsWith('/realms/'), { timeout: 20_000 }).then(() => 'stepup' as const),
    done().then(() => 'done' as const),
  ])
  if (outcome === 'stepup') {
    await completeMfaStepUp(page, DEMO_TOTP_SECRETS[secretKey])
    await act()
    await done()
  }
}

test('settlement approval: md1 tile shows it -> click -> settlement page -> approve -> tile empties', async ({
  browser,
}) => {
  const md = await login(browser, 'md1', 'Md1Pass!')
  const before = await tileCount(md)

  const bd = await login(browser, 'bd1', 'Bd1Pass!')
  const project = await findProjectByCode(bd, D1_SIM_PROJECT_CODE)
  await driveSettlementTo(bd, browser, project.id, 'draft')
  await submitSettlementForApproval(bd, project.id)

  // The submitter sees no actions, only why.
  await expect(bd.getByText('Awaiting a different approver (SoD)')).toBeVisible()
  await expect(bd.getByRole('button', { name: 'Approve' })).toBeDisabled()

  // The tile count goes up by one and links to the whole queue...
  await expectTileCount(md, before + 1)
  await expect(tileOf(md).getByRole('link', { name: /View all/ })).toBeVisible()

  // ...where the request is, with everything an approver needs to pick it, without opening it.
  await md.goto('/approvals')
  const row = md.getByRole('table', { name: 'Pending approvals' }).getByRole('row', { name: new RegExp(D1_SIM_PROJECT_CODE) })
  await expect(row).toBeVisible()
  await expect(row).toContainText(/Bid settlement v\d+/)
  await expect(row).not.toContainText('bid_submission')
  await expect(row).toContainText('margin on sell 0.000%')
  await expect(row).not.toContainText('unknown user')
  await expect(row).toContainText(/managing director/i)

  await row.getByRole('link', { name: /Review/ }).click()
  await expect(md).toHaveURL(new RegExp(`/projects/${project.id}/settlement$`))
  if ((await attemptApprove(md)) === 'blocked') {
    await completeMfaStepUp(md, DEMO_TOTP_SECRETS.md1)
    expect(await attemptApprove(md)).toBe('approved')
  }

  await expectTileCount(md, before)

  // ...and it is on md1's /approvals page under "decided".
  await md.goto('/approvals')
  const decided = md.getByRole('table', { name: 'Recently decided approvals' })
  await expect(decided.getByRole('row', { name: new RegExp(`${D1_SIM_PROJECT_CODE}.*Bid settlement v\\d+.*approved`) }).first()).toBeVisible()
})

test('cost_rate_change: tile -> detail page -> approve; reject needs a reason; submitter has no actions', async ({
  browser,
}) => {
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const before = await tileCount(lead)

  const estimator = await login(browser, 'estimator1', 'Estimator1Pass!')
  const approve = uniqueAmount()
  const reject = uniqueAmount()
  const approveId = await createCostRateRequest(estimator, approve.raw)
  const rejectId = await createCostRateRequest(estimator, reject.raw)

  // Denied role: estimator has no Approvals nav entry and the endpoint refuses it.
  await estimator.goto('/dashboard')
  await expect(estimator.getByRole('link', { name: 'Approvals' })).toHaveCount(0)
  expect((await estimator.request.get('/api/v1/approvals/inbox')).status()).toBe(403)

  // The tile count goes up by two; the requests themselves are found on /approvals, however long the queue is.
  await expectTileCount(lead, before + 2)
  await lead.goto('/approvals')
  const queue = lead.getByRole('table', { name: 'Pending approvals' })
  const row = queue.getByRole('row', { name: new RegExp(approve.shown.replace('.', '\\.')) })
  await expect(row).toBeVisible()
  await expect(row).toContainText('Cost rate change')
  await expect(row).not.toContainText('cost_rate_change')
  await expect(queue.getByRole('row', { name: new RegExp(reject.shown.replace('.', '\\.')) })).toBeVisible()
  await row.getByRole('link', { name: /Review/ }).click()
  await expect(lead).toHaveURL(new RegExp(`/approvals/${approveId}$`))
  await expect(lead.getByRole('heading', { name: 'Cost rate change' })).toBeVisible()
  await decideWithStepUp(
    lead,
    () => lead.getByRole('button', { name: 'Approve' }).click(),
    () => lead.getByText('approved', { exact: true }).first().waitFor(),
    'lead1',
  )

  await expectTileCount(lead, before + 1)

  // Reject requires a reason: the modal's submit stays disabled until typed.
  await lead.goto(`/approvals/${rejectId}`)
  await lead.getByRole('button', { name: 'Reject' }).click()
  const submit = lead.getByRole('dialog').getByRole('button', { name: 'Reject' })
  await expect(submit).toBeDisabled()
  await lead.getByRole('dialog').getByRole('textbox').fill('Rate not supported by the quote')
  await expect(submit).toBeEnabled()
  await decideWithStepUp(
    lead,
    async () => {
      // After a step-up redirect the modal is closed again: reopen and refill.
      if (!(await lead.getByRole('dialog').isVisible())) {
        await lead.getByRole('button', { name: 'Reject' }).click()
        await lead.getByRole('dialog').getByRole('textbox').fill('Rate not supported by the quote')
      }
      await lead.getByRole('dialog').getByRole('button', { name: 'Reject' }).click()
    },
    () => lead.getByText('rejected', { exact: true }).first().waitFor(),
    'lead1',
  )

  await expectTileCount(lead, before)

  // Both decisions are listed under "decided" on /approvals.
  await lead.goto('/approvals')
  const decided = lead.getByRole('table', { name: 'Recently decided approvals' })
  await expect(decided.getByRole('row', { name: new RegExp(approve.shown.replace('.', '\\.')) })).toContainText('approved')
  await expect(decided.getByRole('row', { name: new RegExp(reject.shown.replace('.', '\\.')) })).toContainText('rejected')

  // Submitter: lead1 submits a request routed to their own role. It is
  // listed, flagged, and has no actions anywhere.
  const own = uniqueAmount()
  const ownId = await createCostRateRequest(lead, own.raw)
  await lead.goto('/approvals')
  const pending = lead.getByRole('table', { name: 'Pending approvals' })
  const ownRow = pending.getByRole('row', { name: new RegExp(own.shown.replace('.', '\\.')) })
  await expect(ownRow).toContainText('Awaiting a different approver')
  await expect(ownRow.getByRole('link')).toHaveCount(0)
  await lead.goto(`/approvals/${ownId}`)
  await expect(lead.getByText('Awaiting a different approver')).toBeVisible()
  await expect(lead.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(lead.getByRole('button', { name: 'Reject' })).toHaveCount(0)
})

test('approvals pages have no serious/critical axe violations', async ({ browser }) => {
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const id = await createCostRateRequest(await login(browser, 'estimator1', 'Estimator1Pass!'), uniqueAmount().raw)
  for (const path of ['/approvals', `/approvals/${id}`, '/dashboard']) {
    await lead.goto(path)
    await expect(lead.getByRole('heading', { level: 1 })).toBeVisible()
    const results = await new AxeBuilder({ page: lead }).analyze()
    const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(bad, `${path}: ${bad.map((v) => v.id).join(', ')}`).toEqual([])
  }
})
