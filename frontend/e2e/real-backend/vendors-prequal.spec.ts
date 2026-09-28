import { expect, test } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// Phase 3 gap-fill (docs/ui-qa-brief.md): vendor master, duplicate review,
// and prequalification & certificates were confirmed "no UI at all"
// capabilities (docs/ui-qa/coverage.md section 2). This exercises the new
// VendorsPage/VendorDetailPage/VendorDuplicatesPage against the real
// backend.

test.describe('VendorsPage', () => {
  test('estimator sees the vendor list read-only, and a direct create attempt 403s server-side', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    await page.goto('/vendors')
    await expect(page.getByRole('heading', { name: 'Vendors' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'New vendor' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Review duplicates' })).toHaveCount(0)

    const response = await page.request.post('/api/v1/vendors', {
      headers: await csrfHeaders(page),
      data: { legal_name: 'Should Be Refused Vendor LLC' },
    })
    expect(response.status()).toBe(403)
  })

  test('lead_estimator can create a vendor, check duplicates, and reach its detail page', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/vendors')
    await page.getByRole('button', { name: 'New vendor' }).click()

    const uniqueName = `E2E Vendor ${Date.now()}`
    await page.getByLabel('Legal name').fill(uniqueName)
    await page.getByRole('button', { name: 'Check for duplicates' }).click()
    await expect(page.getByText(/No likely duplicates found\.|Possible duplicates/)).toBeVisible()

    await page.getByRole('button', { name: 'Create vendor' }).click()
    await expect(page.getByRole('link', { name: uniqueName })).toBeVisible()

    await page.getByRole('link', { name: uniqueName }).click()
    await expect(page.getByRole('heading', { name: uniqueName })).toBeVisible()
    await expect(page.getByText('No certificates on file.')).toBeVisible()
  })
})

test.describe('Vendor certificates and prequalification', () => {
  test('lead_estimator can add and verify a certificate, with an expiry badge shown', async ({ page }) => {
    await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')
    await page.goto('/vendors')
    await page.getByRole('button', { name: 'New vendor' }).click()
    const uniqueName = `E2E Cert Vendor ${Date.now()}`
    await page.getByLabel('Legal name').fill(uniqueName)
    await page.getByRole('button', { name: 'Create vendor' }).click()
    await page.getByRole('link', { name: uniqueName }).click()

    const certTypeSelect = page.locator('select').filter({ hasText: '-- Certificate type --' })
    // useCertificateTypes() resolves asynchronously -- the select renders
    // with just its placeholder option first, so check the count only
    // AFTER giving the real options a chance to arrive, not immediately on
    // navigation (a premature check here previously always saw count===1
    // and skipped, even when certificate types genuinely existed).
    let hasCertTypes = false
    try {
      await expect
        .poll(async () => certTypeSelect.locator('option').count(), { timeout: 5_000 })
        .toBeGreaterThan(1)
      hasCertTypes = true
    } catch {
      hasCertTypes = false
    }
    test.skip(!hasCertTypes, 'No certificate types seeded in this environment')

    await certTypeSelect.selectOption({ index: 1 })
    const soon = new Date(Date.now() + 10 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    await page.locator('input[type="date"]').fill(soon)
    await page.getByRole('button', { name: 'Add certificate' }).click()

    await expect(page.getByText(/Expires in \d+d/)).toBeVisible()
    await page.getByRole('button', { name: 'Verify' }).click()
    await expect(page.getByRole('button', { name: 'Verify' })).toHaveCount(0)
  })
})

test.describe('VendorDuplicatesPage', () => {
  test('estimator can view but not resolve duplicate candidates', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    await page.goto('/vendors/duplicates')
    await expect(page.getByRole('heading', { name: 'Vendor duplicate review' })).toBeVisible()
    await expect(page.getByText('Your role can view candidates but not resolve them.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Confirm duplicate' })).toHaveCount(0)
  })
})
