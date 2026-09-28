import { expect, test } from '@playwright/test'
import { ensureProjectMember, findProjectByCode, loginViaKeycloak } from './helpers'

// finish-brief step 3: DELETE /projects/{id}/members/{user_id} and its UI.
// The backend tests cover the lowest allowed role (lead_estimator) and a
// denied role (estimator); this proves the page end to end.
test('a director removes a project member through the confirm modal; an estimator is offered no Remove', async ({
  page,
  browser,
}) => {
  await loginViaKeycloak(page, 'md1', 'Md1Pass!')
  const project = await findProjectByCode(page, 'QA-DEMO')
  await ensureProjectMember(browser, project.id, 'estimator1')

  // estimator1 (a member, but not lead/bd/md) sees the list without any Remove control.
  const estContext = await browser.newContext({ ignoreHTTPSErrors: true })
  const estPage = await estContext.newPage()
  await loginViaKeycloak(estPage, 'estimator1', 'Estimator1Pass!')
  await estPage.goto(`/projects/${project.id}`)
  await expect(estPage.getByRole('heading', { name: 'Members' })).toBeVisible()
  await expect(estPage.getByRole('button', { name: /^Remove / })).toHaveCount(0)

  try {
    await page.goto(`/projects/${project.id}`)
    await page.getByRole('button', { name: 'Remove estimator1' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('estimator1 will lose access')
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByRole('button', { name: 'Remove estimator1' })).toHaveCount(0)

    // The removal is real, not just a hidden row: the server's own member
    // list no longer holds estimator1.
    const me = (await (await estPage.request.get('/api/v1/auth/me')).json()) as { sub: string }
    const members = (await (await page.request.get(`/api/v1/projects/${project.id}/members`)).json()) as {
      user_id: string
    }[]
    expect(members.map((m) => m.user_id)).not.toContain(me.sub)
  } finally {
    await estContext.close()
    await ensureProjectMember(browser, project.id, 'estimator1') // restore the fixture
  }
})
