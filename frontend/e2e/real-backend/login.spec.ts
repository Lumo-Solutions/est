import { expect, test } from '@playwright/test'
import { isMfaDisabledDev, loginViaKeycloak } from './helpers'

// Proves the fix for the "Cookie not found" dev-login blocker documented in
// docs/keycloak-setup.md: Keycloak marks its own login-flow cookies
// Secure+SameSite=None unconditionally, which a real browser refuses to
// send back over plain HTTP. caddy-dev fronts both Keycloak and the
// frontend with a real (self-signed) TLS hop so those cookies actually
// round-trip. No page.route mocking of /auth/me anywhere in this file --
// this drives the real Keycloak login form and asserts a real session.
test('estimator1 logs in through the real Keycloak form and reaches an authenticated session', async ({ page }) => {
  await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')

  const me = await page.request.get('/api/v1/auth/me')
  expect(me.ok()).toBe(true)
  const body = await me.json()
  expect(body.roles).toContain('estimator')

  // The SPA re-fetches /auth/me on load and renders the authenticated
  // AppShell (with a "Sign out" control) instead of the sign-in page.
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
})

// Keycloak (login OTP, set by deploy/keycloak/bootstrap.sh) and the backend
// (step-up bypass + /auth/me's mfa_disabled_dev, app/security/deps.py) are
// switched together by DEV_DISABLE_MFA (`make dev-mfa-off` / `dev-mfa-on`).
// This fails if they ever disagree -- e.g. OTP was demanded while the
// backend says MFA is off, or login skipped OTP while the backend says it is
// on -- and checks the "DEV: MFA disabled" banner tracks the backend flag.
test('login OTP prompt, /auth/me and the DEV: MFA disabled banner all agree on the MFA mode', async ({ page }) => {
  const otpPrompted = await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
  const mfaDisabledDev = await isMfaDisabledDev(page)
  console.log(`[login.spec] MFA mode: ${mfaDisabledDev ? 'OFF (DEV_DISABLE_MFA)' : 'ON'}; login OTP prompted: ${otpPrompted}`)

  expect(otpPrompted, 'Keycloak asks for an OTP at login exactly when the backend says MFA is on').toBe(!mfaDisabledDev)

  await page.goto('/')
  const banner = page.getByTestId('dev-mfa-banner')
  if (mfaDisabledDev) {
    await expect(banner).toHaveText('DEV: MFA disabled')
  } else {
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
    await expect(banner).toHaveCount(0)
  }
})
