import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// The tracked QA screenshots are only rewritten on purpose (UPDATE_QA_SCREENSHOTS=1); a normal run writes to test-results.
const QA_SHOT_DIR = process.env.UPDATE_QA_SCREENSHOTS === '1' ? '../docs/ui-qa/screenshots/ai-first-intake' : 'test-results/qa-screenshots/ai-first-intake'

// AI-first tender intake, real backend, real Keycloak, real Celery workers, real S3, the MOCK provider (no key):
//   create a project -> drop the .ai-demo-pack FOLDER -> the AI reads every file, confident answers are routed
//   without a person -> the tree shows the right groups (class -> discipline -> drawing type) -> the one file the
//   AI is unsure of sits under "Needs your check" and a person files it -> the drawings reach `ready` -> the BOQ
//   import opens pre-filled (the user still runs the dry run) -> a drawing reclassified as a spec leaves the
//   takeoff (archived, not deleted) and comes back when changed again.
// Preconditions (docs/ai-first-intake/report.md): `make up` with a rebuilt backend and workers, `make migrate`,
// `make seed`, AI_PROVIDER=mock and TAKEOFF_PERSIST_GEOMETRY=true in deploy/.env. MFA on or off both work.
// The folder is written by `make dev-ai-demo-pack` too (./.ai-demo-pack/); this spec regenerates it.

const PACK_ROOT = 'Al Reem Package 3'
const FILES = 9

interface TreeItem {
  id: string
  name: string
  path: string | null
  doc_class: string | null
  discipline: string | null
  drawing_type: string | null
  confidence: number | null
  display_status: string
  status_reason: string | null
  classified_by: string | null
  decided_by: string | null
  auto_accepted: boolean
  routed_kind: string | null
  drawing_id: string | null
}
interface Tree {
  items: TreeItem[]
  summary: { total: number; needs_check: number; in_progress: number; packages_processing: number; drawings_total: number; drawings_ready: number; boq_documents: { id: string; name: string }[]; auto_accept_min: number }
}

function writeDemoPack(): string {
  const remote = `/tmp/ai-first-pack-${Date.now()}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'write-ai-demo-pack', '--out', remote], { stdio: 'pipe' })
  const dir = resolve(process.cwd(), '..', '.ai-demo-pack')
  rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  return dir
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.error(`PAGEERROR (${user}): ${e.message}\n${e.stack ?? ''}`))
  await loginViaKeycloak(page, user, pass)
  return page
}

async function getItems(page: Page, projectId: string): Promise<TreeItem[]> {
  const out: TreeItem[] = []
  for (let offset = 0; ; offset += 500) {
    const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents/items?limit=500&offset=${offset}`)
    expect(res.ok(), await res.text()).toBeTruthy()
    const body = (await res.json()) as { items: TreeItem[]; total: number }
    out.push(...body.items)
    if (out.length >= body.total) return out
  }
}

// The tree endpoint returns counts only (summary, groups, folders, packs); the files are paged from /items.
async function getTree(page: Page, projectId: string): Promise<Tree> {
  const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents/tree`)
  expect(res.ok(), await res.text()).toBeTruthy()
  const counts = (await res.json()) as Omit<Tree, 'items'>
  return { ...counts, items: await getItems(page, projectId) }
}

async function waitForTree(page: Page, projectId: string, done: (t: Tree) => boolean, message: string, timeout = 240_000): Promise<Tree> {
  let last: Tree | undefined
  await expect
    .poll(async () => {
      last = await getTree(page, projectId)
      return done(last)
    }, { message, timeout, intervals: [2_000] })
    .toBe(true)
  return last as Tree
}

const byName = (tree: Tree, name: string) => {
  const item = tree.items.find((i) => i.name === name)
  if (!item) throw new Error(`no ${name} in ${tree.items.map((i) => i.name).join(', ')}`)
  return item
}

test.describe.serial('AI-first intake (mock provider)', () => {
  test.setTimeout(900_000)
  const state: { projectId: string; code: string } = { projectId: '', code: '' }

  test('create project -> drop the .ai-demo-pack folder -> groups -> confirm the unsure file -> drawings ready -> BOQ import pre-filled', async ({ browser }) => {
    const pack = writeDemoPack()
    const lead = await login(browser, 'lead1', 'Lead1Pass!')

    // The deployment is on the mock provider; the auto-accept threshold is at its default (only the MD changes it).
    const status = (await (await lead.request.get('/api/v1/ai/status')).json()) as { provider: string; external: boolean; available: boolean }
    expect(status).toMatchObject({ provider: 'mock', external: false, available: true })
    const md = await login(browser, 'md1', 'Md1Pass!')
    const denied = await lead.request.put('/api/v1/admin/intake-settings', { headers: await csrfHeaders(lead), data: { auto_accept_min: 0.5 } })
    expect(denied.status()).toBe(403)
    const set = await md.request.put('/api/v1/admin/intake-settings', { headers: await csrfHeaders(md), data: { auto_accept_min: 0.85 } })
    expect(set.ok(), await set.text()).toBeTruthy()
    await md.context().close()

    // ---- 1. a new project lands on the one project page, with the big drop zone
    state.code = `AIFI-${Date.now().toString(36).toUpperCase()}`
    await lead.goto('/')
    await lead.getByRole('button', { name: 'New project' }).click()
    await lead.getByLabel('Code').fill(state.code)
    await lead.getByLabel('Name').fill('Al Reem Package 3 (AI-first intake)')
    await lead.getByRole('button', { name: 'Create project' }).click()
    await expect(lead).toHaveURL(/\/projects\/[0-9a-f-]+$/)
    state.projectId = /projects\/([0-9a-f-]+)/.exec(lead.url())![1]
    await expect(lead.getByRole('heading', { name: new RegExp(state.code) })).toBeVisible()
    await expect(lead.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeVisible()
    await expect(lead.getByRole('button', { name: 'Choose folder' })).toBeVisible()
    await expect(lead.getByRole('button', { name: 'Choose files' })).toBeVisible()
    // One page: no Overview / Tender documents tabs, an Edit project button instead.
    await expect(lead.getByRole('button', { name: 'Tender documents' })).toHaveCount(0)
    await expect(lead.getByRole('button', { name: 'Edit project' })).toBeVisible()

    // ---- 2. drop the whole FOLDER (webkitdirectory keeps the relative paths)
    await lead.getByTestId('tender-folder-input').setInputFiles(join(pack, PACK_ROOT))
    await expect(lead.getByRole('list', { name: 'Files to upload' }).getByRole('listitem')).toHaveCount(FILES)
    await expect(lead.getByRole('list', { name: 'Files to upload' })).toContainText('01 Drawings')
    await lead.getByRole('button', { name: `Upload ${FILES} files` }).click()

    // ---- 3. the AI reads every file; nobody clicked anything yet
    const tree = await waitForTree(lead, state.projectId, (t) => t.summary.total === FILES && t.summary.in_progress === 0 && t.summary.packages_processing === 0, 'every file read')
    expect(tree.summary.auto_accept_min).toBeCloseTo(0.85)
    const expected: Record<string, [string, string | null, string | null]> = {
      'C-101 Road and Drainage Plan Rev B.dxf': ['drawing', 'roads_civil', 'general_arrangement'],
      'L-201 Landscape Plan Rev A.pdf': ['drawing', 'landscape', 'general_arrangement'],
      'C-102 Storm Drainage Plan and Profile Rev A.pdf': ['drawing', 'stormwater', 'plan_profile'],
      'BOQ Rev 0.xlsx': ['boq', null, null],
      'BOQ Rev 0 (print copy).pdf': ['boq', null, null],
      'Particular Specification.pdf': ['specification', null, null],
      'Addendum No 1.pdf': ['addendum', null, null],
      'Conditions of Contract.pdf': ['contract', null, null],
    }
    for (const [name, [cls, discipline, type]] of Object.entries(expected)) {
      const item = byName(tree, name)
      expect([name, item.doc_class, item.discipline, item.drawing_type]).toEqual([name, cls, discipline, type])
      expect([name, item.classified_by, item.decided_by, item.auto_accepted]).toEqual([name, 'ai', 'ai', true]) // accepted by the threshold, not by a person
      expect(item.confidence).toBeGreaterThanOrEqual(0.85)
    }
    // The drawing someone filed under the BOQ folder followed its content, not the folder.
    expect(byName(tree, 'C-102 Storm Drainage Plan and Profile Rev A.pdf').path).toContain('02 BOQ')
    // The one file the AI cannot tell is waiting for a person.
    const unsure = byName(tree, 'Site visit notes.pdf')
    expect(unsure).toMatchObject({ doc_class: 'other', display_status: 'needs_check', auto_accepted: false, routed_kind: null })
    expect(unsure.confidence).toBeLessThan(0.85)
    expect(tree.summary.needs_check).toBe(1)

    // ---- 4. the page: Needs your check on top, then the organised tree with counts
    await expect(lead.getByRole('heading', { name: 'Needs your check' })).toBeVisible()
    await expect(lead.getByRole('button', { name: 'Confirm Site visit notes.pdf' })).toBeVisible()
    const drawings = lead.getByRole('group', { name: 'Drawing, 3 files' })
    await expect(drawings).toBeVisible()
    await expect(drawings.getByRole('group', { name: 'Roads / civil, 1 file' })).toBeVisible()
    await expect(drawings.getByRole('group', { name: 'Landscape, 1 file' })).toBeVisible()
    await expect(drawings.getByRole('group', { name: 'Stormwater drainage, 1 file' })).toBeVisible()
    await expect(lead.getByRole('group', { name: 'BOQ, 2 files' })).toBeVisible()
    await expect(lead.getByRole('group', { name: 'Specification, 1 file' })).toBeVisible()
    await expect(lead.getByRole('group', { name: 'Addendum, 1 file' })).toBeVisible()
    await expect(lead.getByRole('group', { name: 'Contract / Conditions, 1 file' })).toBeVisible()
    // A small pack opens fully: the stormwater discipline down to its drawing type and its row (confidence, who decided).
    const storm = drawings.getByRole('group', { name: 'Stormwater drainage, 1 file' })
    await expect(storm.getByRole('group', { name: 'Plan & profile / longitudinal section, 1 file' })).toBeVisible()
    const stormRow = storm.getByRole('listitem').filter({ hasText: 'C-102 Storm Drainage Plan and Profile Rev A.pdf' })
    await expect(stormRow).toBeVisible()
    await expect(stormRow).toContainText('AI')
    await expect(stormRow).toContainText(/\d\d%/)

    // The original folders are one click away, and show the drawing where it was filed.
    await lead.getByRole('button', { name: 'Original folders' }).click()
    await expect(lead.getByRole('group', { name: /02 BOQ/ }).getByText('C-102 Storm Drainage Plan and Profile Rev A.pdf')).toBeVisible()
    await lead.getByRole('button', { name: 'By document type' }).click()

    // ---- 5. a person files the unsure one: one click on Change, then the class
    await lead.getByRole('button', { name: 'Change class of Site visit notes.pdf' }).first().click()
    await lead.locator('li').filter({ hasText: 'Site visit notes.pdf' }).first().getByLabel('Class', { exact: true }).selectOption({ label: 'Correspondence' })
    await expect(lead.getByRole('button', { name: 'Confirm Site visit notes.pdf' })).toHaveCount(0, { timeout: 30_000 })
    const filed = byName(await getTree(lead, state.projectId), 'Site visit notes.pdf')
    expect(filed).toMatchObject({ doc_class: 'correspondence', classified_by: 'user', decided_by: 'user', routed_kind: 'register', display_status: 'ready' })

    // ---- 6. intake only classified and indexed the drawings; measuring is on demand
    const indexed = await getTree(lead, state.projectId)
    const drawingItems = indexed.items.filter((i) => i.doc_class === 'drawing')
    expect(drawingItems).toHaveLength(3)
    const drawingState = async (id: string) => (await (await lead.request.get(`/api/v1/drawings/${id}`)).json()) as { status: string; measurement: string }
    for (const item of drawingItems) expect(await drawingState(item.drawing_id!)).toMatchObject({ status: 'indexed', measurement: 'indexed' })
    await expect(lead.getByRole('heading', { name: 'Drawings to measure' })).toBeVisible({ timeout: 45_000 })
    // Opening one drawing measures it now (what the takeoff page does) ...
    const opened = await lead.request.post(`/api/v1/drawings/${drawingItems[0].drawing_id}/measure`, { headers: await csrfHeaders(lead) })
    expect(opened.status()).toBe(202)
    // ... and "Measure all" queues the rest behind it (lead_estimator and above).
    const bulk = await lead.request.post(`/api/v1/projects/${state.projectId}/drawings/measure`, {
      headers: await csrfHeaders(lead),
      data: { disciplines: ['roads_civil', 'landscape', 'stormwater'] },
    })
    expect(bulk.status()).toBe(202)
    expect(await bulk.json()).toMatchObject({ matched: 2 })
    const ready = await waitForTree(lead, state.projectId, (t) => t.summary.drawings_total === 3 && t.summary.drawings_ready === 3 && t.summary.in_progress === 0, 'three drawings measured', 420_000)
    expect(ready.summary.needs_check).toBe(0)
    for (const item of drawingItems) await expect.poll(async () => (await drawingState(item.drawing_id!)).measurement, { timeout: 420_000, intervals: [3_000] }).toBe('measured')
    await expect(lead.getByText('3 of 3 drawings ready')).toBeVisible({ timeout: 60_000 })

    // ---- 7. the Excel BOQ is ready to import: the wizard opens pre-filled; the dry run is still the user's to run
    const boq = byName(ready, 'BOQ Rev 0.xlsx')
    expect(ready.summary.boq_documents.map((d) => d.id)).toContain(boq.id)
    await lead.getByLabel('BOQ document').selectOption({ label: 'BOQ Rev 0.xlsx' })
    await lead.getByRole('link', { name: 'Import BOQ' }).click()
    await expect(lead).toHaveURL(new RegExp(`/projects/${state.projectId}/boq/import\\?document=${boq.id}`))
    await expect(lead.getByRole('status').filter({ hasText: 'Pre-filled from tender document BOQ Rev 0.xlsx' })).toBeVisible({ timeout: 30_000 })
    await expect(lead.getByLabel('Header row')).toHaveValue('4')
    await expect(lead.getByLabel('Item No column *')).toHaveValue('Item')
    await expect(lead.getByLabel('Description column *')).toHaveValue('Description')
    await expect(lead.getByLabel('Quantity column')).toHaveValue('Qty')
    await expect(lead.getByRole('button', { name: 'Commit' })).toBeDisabled() // nothing ran on its own
    await lead.getByRole('button', { name: 'Preview' }).click()
    await expect(lead.getByRole('button', { name: 'Commit' })).toBeEnabled({ timeout: 30_000 })
    await lead.getByRole('button', { name: 'Commit' }).click()
    await expect(lead).toHaveURL(new RegExp(`/projects/${state.projectId}/boq$`), { timeout: 30_000 })
    const items = (await (await lead.request.get(`/api/v1/projects/${state.projectId}/boq-items`)).json()) as { item_no: string }[]
    expect(items.map((i) => i.item_no)).toEqual(expect.arrayContaining(['1', '1.1', '2.1', '5.3', '6.2']))
    await lead.context().close()
  })

  test('a drawing reclassified as a spec leaves the takeoff (archived, not deleted) and returns when changed back', async ({ browser }) => {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    const before = await getTree(lead, state.projectId)
    const sheet = byName(before, 'C-102 Storm Drainage Plan and Profile Rev A.pdf')
    const drawingId = sheet.drawing_id!
    const listed = async () => ((await (await lead.request.get(`/api/v1/projects/${state.projectId}/drawings`)).json()) as { id: string }[]).map((d) => d.id)
    expect(await listed()).toContain(drawingId)

    await lead.goto(`/projects/${state.projectId}`)
    await lead.getByRole('button', { name: 'Change class of C-102 Storm Drainage Plan and Profile Rev A.pdf' }).click()
    const dialog = lead.getByRole('dialog', { name: /Change class of C-102/ })
    await dialog.getByLabel('Class', { exact: true }).selectOption({ label: 'Specification' })
    await dialog.getByRole('button', { name: 'Apply class' }).click()
    // A routed drawing leaving the takeoff asks first.
    const confirm = lead.getByRole('dialog', { name: 'Take this out of the takeoff?' })
    await expect(confirm).toContainText('measurements are archived, not deleted')
    await confirm.getByRole('button', { name: 'Change class' }).click()

    const after = await waitForTree(lead, state.projectId, (t) => byName(t, sheet.name).doc_class === 'specification' && byName(t, sheet.name).display_status === 'ready' && t.summary.drawings_total === 2, 'reclassified')
    expect(byName(after, sheet.name)).toMatchObject({ classified_by: 'user', decided_by: 'user', routed_kind: 'register', drawing_id: null, discipline: null, drawing_type: null })
    expect(after.summary.drawings_total).toBe(2)
    expect(await listed()).not.toContain(drawingId) // out of the takeoff
    expect((await lead.request.get(`/api/v1/drawings/${drawingId}`)).ok()).toBeTruthy() // archived, not deleted
    await expect(lead.getByRole('group', { name: 'Specification, 2 files' })).toBeVisible()

    // Changing its mind restores the same drawing without running extraction again.
    await lead.getByRole('button', { name: 'Change class of C-102 Storm Drainage Plan and Profile Rev A.pdf' }).click()
    const again = lead.getByRole('dialog', { name: /Change class of C-102/ })
    await again.getByLabel('Class', { exact: true }).selectOption({ label: 'Drawing' })
    await again.getByLabel('Discipline').selectOption({ label: 'Stormwater drainage' })
    await again.getByLabel('Drawing type').selectOption({ label: 'Plan & profile / longitudinal section' })
    await again.getByRole('button', { name: 'Apply class' }).click()
    const restored = await waitForTree(lead, state.projectId, (t) => byName(t, sheet.name).doc_class === 'drawing' && byName(t, sheet.name).display_status === 'ready', 'restored')
    expect(byName(restored, sheet.name)).toMatchObject({ drawing_id: drawingId, discipline: 'stormwater', drawing_type: 'plan_profile', decided_by: 'user' })
    expect(await listed()).toContain(drawingId)
    await lead.context().close()
  })

  test('the project page is accessible and does not overflow at 1440, 1280 and 1024', async ({ browser }) => {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    for (const width of [1440, 1280, 1024]) {
      await lead.setViewportSize({ width, height: 1900 })
      await lead.goto(`/projects/${state.projectId}`)
      await expect(lead.getByRole('group', { name: 'Drawing, 3 files' })).toBeVisible()
      await lead.waitForTimeout(400)
      const { scrollWidth, clientWidth } = await lead.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }))
      expect(scrollWidth, `project page overflows sideways at ${width}px`).toBeLessThanOrEqual(clientWidth + 1)
      mkdirSync(QA_SHOT_DIR, { recursive: true })
      await lead.screenshot({ path: `${QA_SHOT_DIR}/project-page-${width}.png`, fullPage: true })
    }
    const axe = await new AxeBuilder({ page: lead }).analyze()
    const serious = axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })), null, 2)).toEqual([])

    // Edit project opens as a drawer (old Overview fields + members) and closes with Escape.
    await lead.getByRole('button', { name: 'Edit project' }).click()
    const drawer = lead.getByRole('dialog', { name: 'Edit project' })
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole('heading', { name: 'Members' })).toBeVisible()
    await lead.screenshot({ path: `${QA_SHOT_DIR}/edit-project-drawer.png` })
    await lead.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
    await lead.context().close()
  })

  test('old ?tab= URLs land on the one project page', async ({ browser }) => {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    await lead.goto(`/projects/${state.projectId}?tab=tender-documents`)
    await expect(lead).toHaveURL(new RegExp(`/projects/${state.projectId}$`))
    await lead.goto(`/projects/${state.projectId}?tab=overview`)
    await expect(lead).toHaveURL(new RegExp(`/projects/${state.projectId}$`))
    await expect(lead.getByRole('group', { name: 'Drawing, 3 files' })).toBeVisible()
    await lead.context().close()
  })
})
