import { expect, test } from '@playwright/test'

// Smoke test: an unauthenticated visitor lands on the login page and the
// sign-in link points at the backend's OIDC entry point. Full login through
// Keycloak needs a running compose stack, so it is not driven here -- this
// only proves the frontend's unauthenticated shell renders and wires up
// correctly.
test('unauthenticated visitor sees the sign-in page', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/problem+json',
      body: JSON.stringify({
        type: 'urn:installtec:unauthorized',
        title: 'Authentication required',
        status: 401,
      }),
    }),
  )

  await page.goto('/')

  const signIn = page.getByRole('link', { name: 'Sign in' })
  await expect(signIn).toBeVisible()
  await expect(signIn).toHaveAttribute('href', /\/api\/v1\/auth\/login\?next=/)
})
