import { expect, test } from '@playwright/test'
import { findProjectByCode, loginViaKeycloak } from './helpers'

// finish-brief step 3: the dev-only admin1 (platform_admin) demo user. Its one
// exclusive action -- "Resolve tenant" on a quarantined email whose tenant
// could not be determined -- was untestable before because no such user
// existed (and the live realm had no platform_admin role at all; see
// deploy/keycloak/bootstrap.sh's ensure_realm_role).
test('admin1 (platform_admin) can log in and is offered Resolve tenant on unknown-tenant quarantined mail', async ({
  page,
  browser,
}) => {
  const mdContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const mdPage = await mdContext.newPage()
  await loginViaKeycloak(mdPage, 'md1', 'Md1Pass!')
  const project = await findProjectByCode(mdPage, 'QA-DEMO')
  await mdContext.close()

  await loginViaKeycloak(page, 'admin1', 'Admin1Pass!')
  const me = await (await page.request.get('/api/v1/auth/me')).json()
  expect(me.roles).toEqual(['platform_admin'])
  expect(me.username).toBe('admin1')

  await page.goto(`/projects/${project.id}/procurement/quarantine`)
  await expect(page.getByRole('heading', { name: /quarantine/i })).toBeVisible()
  // The dev DB holds quarantined mail with no resolved tenant (seeded by the
  // inbound-email simulations); each such row offers the platform_admin-only action.
  await expect(page.getByRole('button', { name: 'Resolve tenant' }).first()).toBeVisible({ timeout: 15_000 })
})
