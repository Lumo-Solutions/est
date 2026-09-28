import { expect, test } from '@playwright/test'
import {
  completeMfaStepUp,
  isMfaDisabledDev,
  D1_SIM_PROJECT_CODE,
  findProjectByCode,
  loginViaKeycloak,
  submitSettlementForApproval,
} from './helpers'
import { DEMO_TOTP_SECRETS } from './totp'

// Phase 3 gap-fill (docs/ui-qa-brief.md): every window.prompt call site was
// replaced with TextPromptModal (frontend/src/components). These tests
// prove the *mechanism* end to end on two of the six call sites (dismiss on
// QuarantineQueuePage, reject on SettlementPage) -- the other four use the
// identical component with the same open/validate/submit shape, so they're
// not each independently re-tested here. Deliberately no
// page.on('dialog') handler anywhere in this file: a leftover native
// window.prompt would hang the test waiting on a dialog nothing here
// answers, which is itself a stronger regression signal than asserting its
// absence directly.

test.describe('QuarantineQueuePage: dismiss uses a modal, not window.prompt', () => {
  test('the modal opens, requires non-empty text, and Cancel leaves the row untouched', async ({ page }) => {
    await loginViaKeycloak(page, 'procurement1', 'Procurement1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}/procurement/quarantine`)

    const firstRow = page.locator('table tbody tr').first()
    await expect(firstRow).toBeVisible()
    const rowText = await firstRow.textContent()

    await firstRow.getByRole('button', { name: 'Dismiss' }).click()

    // A real dialog element, not a native prompt (no dialog handler is
    // registered anywhere in this file -- if window.prompt still fired,
    // this would hang until the test's own timeout instead).
    const dialog = page.getByRole('dialog', { name: 'Dismiss' })
    await expect(dialog).toBeVisible()
    const submitButton = dialog.getByRole('button', { name: 'Dismiss' })
    await expect(submitButton).toBeDisabled()

    await dialog.locator('textarea').fill('test note, not actually submitted')
    await expect(submitButton).toBeEnabled()

    // Cancel, not Dismiss -- this row is real seeded demo data other specs
    // also read from (docs/ui-qa/log.md's quarantine-queue coverage), so
    // this test proves the modal mechanism without consuming it.
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.locator('table tbody tr').first()).toHaveText(rowText ?? '')
  })
})

test.describe('SettlementPage: reject uses a modal, not window.prompt', () => {
  test('bd1 submits, md1 rejects via the modal with a real MFA step-up, and the note is recorded', async ({
    page,
    browser,
  }) => {
    await loginViaKeycloak(page, 'bd1', 'Bd1Pass!')
    const project = await findProjectByCode(page, D1_SIM_PROJECT_CODE)
    await submitSettlementForApproval(page, project.id)

    const mdContext = await browser.newContext({ ignoreHTTPSErrors: true })
    const mdPage = await mdContext.newPage()
    await loginViaKeycloak(mdPage, 'md1', 'Md1Pass!')
    await mdPage.goto(`/projects/${project.id}/settlement`)

    const rejectButton = mdPage.getByRole('button', { name: 'Reject' })
    await expect(rejectButton).toBeEnabled()
    await rejectButton.click()

    const dialog = mdPage.getByRole('dialog', { name: 'Reject settlement' })
    await expect(dialog).toBeVisible()
    const submitButton = dialog.getByRole('button', { name: 'Reject' })
    await expect(submitButton).toBeDisabled()

    const note = `Phase 3 modal-replacement test ${Date.now()}`
    await dialog.locator('textarea').fill(note)
    await expect(submitButton).toBeEnabled()
    await submitButton.click()

    // First attempt 403s with step-up-required (md1's fresh login is
    // bronze-only, same as every other decide() call in this suite) --
    // lib/api.ts turns that into a full-page redirect through Keycloak's
    // real re-authentication, not a UI-level retry.
    //
    // With DEV_DISABLE_MFA on (dev/test only) that first submit already
    // rejected -- there is no step-up to complete or retry.
    if (!(await isMfaDisabledDev(mdPage))) {
      await completeMfaStepUp(mdPage, DEMO_TOTP_SECRETS.md1)

      // The dialog closed on the first submit attempt (before the step-up
      // redirect); the retry after step-up needs the same action taken again
      // from the now-reloaded page.
      await mdPage.getByRole('button', { name: 'Reject' }).click()
      await mdPage.getByRole('dialog', { name: 'Reject settlement' }).locator('textarea').fill(note)
      await mdPage.getByRole('dialog', { name: 'Reject settlement' }).getByRole('button', { name: 'Reject' }).click()
    }

    // SettlementPage.tsx's Phase 4 restyle renders the status as a shared
    // Badge (docs/ui-design-system.md section 4.8) rather than plain
    // " -- rejected -- " text, so the version number and the status badge
    // are asserted separately instead of as one literal string.
    await expect(mdPage.getByText(/^v\d+$/)).toBeVisible()
    await expect(mdPage.getByText('rejected', { exact: true })).toBeVisible()
    await mdContext.close()
  })
})
