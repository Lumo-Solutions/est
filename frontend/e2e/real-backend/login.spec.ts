import { expect, test } from '@playwright/test'
import { loginViaKeycloak } from './helpers'

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
