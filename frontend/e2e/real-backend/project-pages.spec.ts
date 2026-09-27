import { expect, test } from '@playwright/test'
import { csrfHeaders, findProjectByCode, loginViaKeycloak } from './helpers'

// Phase 2 UI QA (docs/ui-qa-brief.md) -- ProjectsListPage, ProjectDetailPage,
// SheetIndexPage, TakeoffViewerPage, as estimator (the role that actually
// uses these day to day). See docs/ui-qa/issues.md for the full writeup of
// what each test below guards against.

test.describe('ProjectsListPage', () => {
  test('estimator does not see the create-project affordance, and a direct create attempt 403s server-side', async ({
    page,
  }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    await page.goto('/')

    // hasRole(...CREATE_ROLES) client-side gate (ProjectsListPage.tsx) --
    // UX nicety only, the real enforcement is the API call below.
    await expect(page.getByRole('button', { name: 'New project' })).toHaveCount(0)

    const response = await page.request.post('/api/v1/projects', {
      headers: await csrfHeaders(page),
      data: { code: 'QA-P2-SHOULD-FAIL', name: 'estimator should not be able to create this' },
    })
    expect(response.status()).toBe(403)
  })
})

test.describe('ProjectDetailPage', () => {
  test('a nonexistent project id surfaces a "not found" error quickly, not an indefinite Loading state', async ({
    page,
  }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    await page.goto('/projects/00000000-0000-0000-0000-000000000000')

    // Regression guard: react-query's default retry (3x, exponential
    // backoff) used to retry this 404 as if it might be transient, holding
    // the page on "Loading..." for ~7-10s with no way to tell it apart from
    // a slow-but-working fetch. App.tsx's queryClient now treats any 4xx as
    // non-retryable, so this should resolve within a couple of seconds.
    await expect(page.getByText(/not found/i)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('link', { name: '← Projects' })).toBeVisible()
  })

  test('a real project renders with a working back link to the projects list', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}`)

    await expect(page.getByRole('heading', { name: new RegExp(`^${project.code}`) })).toBeVisible()
    const back = page.getByRole('link', { name: '← Projects' })
    await expect(back).toBeVisible()
    await back.click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  })

  test('deep link + hard refresh both land on the same project page', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const project = await findProjectByCode(page, 'QA-DEMO')
    await page.goto(`/projects/${project.id}`)
    await expect(page.getByRole('heading', { name: new RegExp(`^${project.code}`) })).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { name: new RegExp(`^${project.code}`) })).toBeVisible()
  })
})

test.describe('Unmatched routes', () => {
  test('an unknown path renders a 404 page instead of a blank screen', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')

    // Regression guard: App.tsx had no path="*" route at all -- react-router
    // rendered nothing (not even the AppShell chrome) and logged "No routes
    // matched location" to the console for any URL that didn't exactly match
    // a known pattern.
    await page.goto('/this-page-does-not-exist-at-all')
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
    await expect(page.getByRole('link', { name: '← Projects' })).toBeVisible()
  })
})

test.describe('SheetIndexPage and TakeoffViewerPage', () => {
  // GEO-TEST is a long-lived fixture (see docs/ui-qa/log.md) with a DXF
  // drawing that already has 2 indexed sheets and extracted entities --
  // exactly the read-only data these two pages need, without depending on a
  // fresh ingest run completing during this spec.
  const GEO_TEST_PROJECT_ID = 'cef24c29-5a75-435e-9c78-11a19b115a2f'
  const GEO_TEST_DRAWING_ID = '747f76c1-24f6-43c9-b75a-29e3ead382cb'

  test('sheet index lists sheets, links to the viewer, and links back to the project', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const consoleErrors: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text())
    })

    await page.goto(`/projects/${GEO_TEST_PROJECT_ID}/drawings/${GEO_TEST_DRAWING_ID}`)
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('row')).toHaveCount(3) // header + 2 sheets

    const back = page.getByRole('link', { name: '← Back to project' })
    await expect(back).toBeVisible()
    await back.click()
    await expect(page).toHaveURL(new RegExp(`/projects/${GEO_TEST_PROJECT_ID}$`))

    expect(consoleErrors).toEqual([])
  })

  test('takeoff viewer renders a sheet with a working back link and no console errors', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
    const consoleErrors: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text())
    })

    await page.goto(`/projects/${GEO_TEST_PROJECT_ID}/drawings/${GEO_TEST_DRAWING_ID}/sheets/0`)
    await expect(page.getByText('Measurements')).toBeVisible()

    const back = page.getByRole('link', { name: '← Sheets' })
    await expect(back).toBeVisible()
    await back.click()
    await expect(page).toHaveURL(new RegExp(`/drawings/${GEO_TEST_DRAWING_ID}$`))

    expect(consoleErrors).toEqual([])
  })

  test('a nonexistent sheet index shows an error, not an indefinite Loading state', async ({ page }) => {
    await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')

    // Regression guard: TakeoffViewerPage's render gate was
    // `if (sheetLoading || !sheet || !drawing) return <Loading/>` -- once
    // useSheet's query settled into an error state (sheetLoading false,
    // sheet still undefined), `!sheet` stayed true forever, so a bad sheet
    // index looked identical to a page that was still loading, forever.
    await page.goto(`/projects/${GEO_TEST_PROJECT_ID}/drawings/${GEO_TEST_DRAWING_ID}/sheets/999`)
    await expect(page.getByText(/not found|404/i)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('link', { name: '← Sheets' })).toBeVisible()
  })
})
