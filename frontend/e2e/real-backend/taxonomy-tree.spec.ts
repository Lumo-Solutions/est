import { expect, test } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// Phase 3 gap-fill (docs/ui-qa-brief.md): TaxonomyAdmin.tsx replaced its flat
// dropdown-based parent-id form with an actual hierarchical tree (expand/
// collapse, inline rename, add-child, move-with-confirmation) -- see
// docs/ui-qa/log.md's Phase 3 section. Existing role-gating and mutation
// wiring are unchanged (already covered by
// admin-audit-permissions.spec.ts's AdminPage tests); this file exercises
// the new tree interactions specifically. Uses a random suffix so repeated
// runs don't collide with nodes a previous run left behind.
//
// Locator note: every node's "Move to" <select> lists every OTHER node
// (except its own descendants) as an <option>, so a naive
// `locator('li').filter({ hasText: name })` matches not just the node's
// own row but also every other row that happens to offer it as a move
// target. Scoping via the node's own <span> (never inside a <select>) and
// walking up to its nearest <li>, then taking the first <div> descendant
// (always the row's own header, since it's the first element rendered
// inside that <li>) avoids that trap.

const SUFFIX = Math.random().toString(36).slice(2, 8)
const ROOT_CODE = `QA-ROOT-${SUFFIX}`
const ROOT_NAME = `QA Root ${SUFFIX}`
const CHILD_CODE = `QA-CHILD-${SUFFIX}`
const CHILD_NAME = `QA Child ${SUFFIX}`
const RENAMED_NAME = `QA Root Renamed ${SUFFIX}`

function rowFor(page: import('@playwright/test').Page, name: string) {
  const nameSpan = page.locator('span', { hasText: name }).first()
  const li = nameSpan.locator('xpath=ancestor::li[1]')
  const header = li.locator('div').first()
  return { li, header }
}

test('managing_director can add a root node, add a child under it, expand/collapse, rename, toggle active, and move a node with confirmation', async ({ page }) => {
  await loginViaKeycloak(page, 'md1', 'Md1Pass!')
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Taxonomy' }).click()

  // Add a root node.
  await page.getByPlaceholder('Code').fill(ROOT_CODE)
  await page.getByPlaceholder('Name').fill(ROOT_NAME)
  await page.getByRole('button', { name: 'Add root node' }).click()
  let root = rowFor(page, ROOT_NAME)
  await expect(root.header.getByText(ROOT_NAME, { exact: true })).toBeVisible()

  // No expand/collapse toggle yet -- it has no children.
  await expect(root.header.getByRole('button', { name: /Expand|Collapse/ })).toHaveCount(0)

  // Add a child under it.
  await root.header.getByRole('button', { name: 'Add child' }).click()
  const addChildForm = root.li.locator('form').filter({ has: page.getByPlaceholder('Code') })
  await addChildForm.getByPlaceholder('Code').fill(CHILD_CODE)
  await addChildForm.getByPlaceholder('Name').fill(CHILD_NAME)
  await addChildForm.getByRole('button', { name: 'Add' }).click()
  let child = rowFor(page, CHILD_NAME)
  await expect(child.header.getByText(CHILD_NAME, { exact: true })).toBeVisible()

  // Now the root has a collapse toggle (it has a child) -- collapse, child
  // disappears; expand, it's back.
  // Note: getByText also matches CHILD_NAME inside every OTHER node's
  // "Move to" <option> (which stays in the DOM regardless of collapse
  // state), so these two checks scope to <span> -- the row-label element
  // only ever used for a node's own visible name, never an <option>.
  const collapseBtn = root.header.getByRole('button', { name: /Collapse/ })
  await expect(collapseBtn).toBeVisible()
  await collapseBtn.click()
  await expect(page.locator('span', { hasText: CHILD_NAME })).toHaveCount(0)
  await root.header.getByRole('button', { name: /Expand/ }).click()
  await expect(page.locator('span', { hasText: CHILD_NAME }).first()).toBeVisible()

  // Rename the root node inline. Scoped via the (page-unique, since only one
  // row is ever in rename mode) Save button rather than root.header, which
  // resolves through the name span -- that span is exactly what disappears
  // once rename mode replaces it with a form, which would otherwise break
  // root.header's own lazy resolution the moment Rename is clicked.
  await root.header.getByRole('button', { name: 'Rename', exact: true }).click()
  const saveButton = page.getByRole('button', { name: 'Save' })
  const renameForm = saveButton.locator('xpath=ancestor::form[1]')
  await renameForm.locator('input').fill(RENAMED_NAME)
  const patchResponse = page.waitForResponse((r) => r.url().includes('/api/v1/taxonomy/') && r.request().method() === 'PATCH')
  await saveButton.click()
  // Regression guard for a real bug this test found live: update_node
  // (app/services/taxonomy.py) never refreshed updated_at after its own
  // flush, so every rename/active-toggle 500'd the moment
  // TradeNodeOut.model_validate tried to read it (MissingGreenlet under
  // the async driver) -- fixed alongside this test, see
  // backend/tests/integration/test_taxonomy_update_refresh.py for the
  // service-level regression test.
  expect((await patchResponse).status()).toBe(200)
  root = rowFor(page, RENAMED_NAME)
  await expect(root.header.getByText(RENAMED_NAME, { exact: true })).toBeVisible()

  // Toggle active off, then back on. Uses .click() + waiting for the PATCH
  // response rather than .check()/.uncheck(): this checkbox has no
  // optimistic update (same as every other mutation in this app), so
  // clicking it flips the DOM checkbox instantly but React's controlled
  // re-render -- still bound to the pre-mutation server value until the
  // query invalidates and refetches -- snaps it back within the same
  // tick, which Playwright's own pre/post-state check on .check()/
  // .uncheck() reads as "didn't change." That's a real (if minor,
  // consistent-with-the-rest-of-the-app) lack-of-optimistic-UI
  // characteristic, not a bug worth fixing in this pass -- waiting for
  // the round trip before asserting the final state works either way.
  const activeCheckbox = root.header.getByLabel('Active')
  await expect(activeCheckbox).toBeChecked()
  let patchDone = page.waitForResponse((r) => r.url().includes('/api/v1/taxonomy/') && r.request().method() === 'PATCH')
  await activeCheckbox.click()
  expect((await patchDone).status()).toBe(200)
  await expect(root.header.getByText(RENAMED_NAME, { exact: true })).toHaveClass(/line-through/)
  patchDone = page.waitForResponse((r) => r.url().includes('/api/v1/taxonomy/') && r.request().method() === 'PATCH')
  await activeCheckbox.click()
  expect((await patchDone).status()).toBe(200)
  await expect(root.header.getByText(RENAMED_NAME, { exact: true })).not.toHaveClass(/line-through/)

  // Move the child node to root (no parent), via the confirmation modal --
  // re-fetch the child row first since the root's rename re-rendered the
  // tree. Regression guard for a second real bug this test found live:
  // move_node (app/services/taxonomy.py) had the exact same missing-
  // updated_at-refresh bug as update_node (see
  // backend/tests/integration/test_taxonomy_update_refresh.py), just on a
  // different code path -- it already refreshed path/level for the same
  // underlying reason (its own pre-existing comment) but missed
  // updated_at, so every move 500'd until fixed alongside this test.
  child = rowFor(page, CHILD_NAME)
  await child.header.getByRole('combobox').selectOption('__root__')
  await expect(page.getByRole('dialog', { name: 'Move node' })).toBeVisible()
  const moveResponse = page.waitForResponse((r) => r.url().includes('/move') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Move' }).click()
  expect((await moveResponse).status()).toBe(200)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // The child (now a root itself) should have lost its "Move to root" option.
  child = rowFor(page, CHILD_NAME)
  await expect(child.header.locator('option', { hasText: 'root (no parent)' })).toHaveCount(0)

  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.waitForTimeout(200)
  expect(errors).toEqual([])
})

test('estimator sees the taxonomy tree read-only, and a direct POST /taxonomy 403s server-side', async ({ page }) => {
  await loginViaKeycloak(page, 'estimator1', 'Estimator1Pass!')
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Taxonomy' }).click()

  await expect(page.getByText('Your role can view the taxonomy but not edit it.')).toBeVisible()
  await expect(page.getByPlaceholder('Code')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Rename', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add child' })).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveCount(0)

  const response = await page.request.post('/api/v1/taxonomy', {
    headers: await csrfHeaders(page),
    data: { code: 'SHOULD-403', name: 'Should be refused' },
  })
  expect(response.status()).toBe(403)
})
