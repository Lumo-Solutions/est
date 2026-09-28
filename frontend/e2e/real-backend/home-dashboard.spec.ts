import { expect, test } from '@playwright/test'
import { loginViaKeycloak } from './helpers'

// Phase 3 gap-fill (docs/ui-qa-brief.md), last item: home dashboard per
// role. See docs/ui-qa/log.md's Phase 3 section for the full writeup and
// which endpoints back which tile.

test('lead_estimator sees the dashboard nav link and its tiles load without error', async ({ page }) => {
  await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible()

  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  // All four tiles a lead_estimator qualifies for should render without an
  // error state -- either a real count or an empty-state message, never
  // "Failed to load."
  await expect(page.getByText('Approvals waiting for me')).toBeVisible()
  await expect(page.getByText('Vendor duplicates open')).toBeVisible()
  await expect(page.getByText('Certificates expiring within 30 days')).toBeVisible()
  await expect(page.getByText('Failed to load.')).toHaveCount(0)

  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(err.message))
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  expect(errors).toEqual([])
})

test('estimator sees the dashboard but no cross-project tiles, with an honest explanation instead of a fake one', async ({
  page,
}) => {
  await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await expect(page.getByText('Approvals waiting for me')).toHaveCount(0)
  await expect(page.getByText('Vendor duplicates open')).toHaveCount(0)
  await expect(page.getByText(/no cross-project summary/i)).toBeVisible()
})

test('managing_director sees every tile', async ({ page }) => {
  await loginViaKeycloak(page, 'md1', 'Md1Pass!')
  await page.goto('/dashboard')

  await expect(page.getByText('Approvals waiting for me')).toBeVisible()
  await expect(page.getByText('Quarantined mail needing review')).toBeVisible()
  await expect(page.getByText('Vendor duplicates open')).toBeVisible()
  await expect(page.getByText('Certificates expiring within 30 days')).toBeVisible()
})
