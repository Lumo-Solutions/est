import { expect, test } from '@playwright/test'
import { completeKeycloakLogin, loginViaKeycloak } from './helpers'

// Sign-out must end the Keycloak SSO session, not just our own: before this
// fix the logout was a fetch() whose redirect chain the browser never visited,
// so Keycloak's own cookies survived and the next "Sign in" silently logged
// the previous user straight back in. Run with MFA off AND on (make
// dev-mfa-off / dev-mfa-on) -- the flow must hold in both.
test.describe('sign out', () => {
  test('ends the SSO session: Sign in asks for credentials again, and a different user can then log in', async ({
    page,
  }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/')
    await expect(page.getByRole('banner').getByText('lead1')).toBeVisible()

    // Real click on the header button -> top-level form POST -> 303 chain
    // through Keycloak's end-session -> the SPA's signed-out page.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/signed-out$/)
    await expect(page.getByRole('heading', { name: 'You have been signed out' })).toBeVisible()

    // Our own server-side session is gone too.
    const me = await page.request.get('/api/v1/auth/me')
    expect(me.status()).toBe(401)

    // The point of the fix: "Sign in" must show the credential form, NOT
    // silently reuse lead1's still-alive Keycloak session.
    await page.getByRole('link', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/\/realms\/installtec\//)
    await expect(page.locator('#username')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()

    // ...and a different user can log in from that same form.
    await completeKeycloakLogin(page, 'bd1', 'Bd1Pass!')
    await page.goto('/')
    await expect(page.getByRole('banner').getByText('bd1', { exact: true })).toBeVisible()
    await expect(page.getByRole('banner').getByText('lead1')).toHaveCount(0)
  })

  test('the signed-out page is public: it renders without a session and does not auto sign in', async ({ page }) => {
    await page.goto('/signed-out')
    await expect(page.getByRole('heading', { name: 'You have been signed out' })).toBeVisible()
    await expect(page).toHaveURL(/\/signed-out$/)
  })
})
