import { execFileSync } from 'node:child_process'
import { mkdtempSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, ensureProjectMember, loginViaKeycloak } from './helpers'

// Tender document intake, real backend, real Keycloak, real Celery workers, real S3, the MOCK AI provider.
// A fresh project per run (so nothing is a duplicate of an earlier run and the shared D1-SIM fixture is
// untouched) and a per-run salted copy of the synthetic pack (backend/app/intake/sample_pack.py, written by
// `python -m app.cli write-tender-pack`). The AI reads every file; confident answers are routed without a
// person, so this spec checks what ended up where, who may act on what is left, and the downstream effects
// (drawings ready, BOQ wizard pre-filled, addendum revision, settlement flag, register). The AI-first flow
// itself, on the demo pack, is in ai-first-intake.spec.ts.

interface TreeItem {
  id: string
  name: string
  path: string | null
  doc_class: string | null
  display_status: string
  status_reason: string | null
  status: string
  decided_by: string | null
  auto_accepted: boolean
  flags: string[]
  routed_kind: string | null
  drawing_id: string | null
}
interface Tree {
  items: TreeItem[]
  summary: { total: number; needs_check: number; in_progress: number; packages_processing: number; drawings_total: number; drawings_ready: number; boq_documents: { id: string; name: string }[]; by_class: Record<string, number> }
}
interface Doc {
  id: string
  original_filename: string
  archive_path: string | null
  status: string
  doc_class: string | null
  routed_kind: string | null
  routed_ref: Record<string, unknown>
  supersedes_id: string | null
  revision_label: string | null
  safety_status: string
  flags: string[]
  classified_by: string | null
  auto_accepted: boolean
}

const PACK_FILES = 18 // top-level files in the pack; the zip adds 4 more documents (the zip itself is not listed)
const SHOWN_DOCS = PACK_FILES - 1 + 4

function writePack(salt: string, extra = 0): { dir: string; files: string[] } {
  const remote = `/tmp/pack-${salt}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'write-tender-pack', '--out', remote, '--salt', salt, '--extra', String(extra)], { stdio: 'pipe' })
  const dir = mkdtempSync(join(tmpdir(), 'tender-pack-'))
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  return { dir, files: readdirSync(dir).sort() }
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

async function waitForRead(page: Page, projectId: string, expected: number, timeout = 240_000): Promise<Tree> {
  let tree: Tree | undefined
  await expect
    .poll(
      async () => {
        tree = await getTree(page, projectId)
        return tree.summary.total >= expected && tree.summary.in_progress === 0 && tree.summary.packages_processing === 0
      },
      { timeout, intervals: [2_000], message: `${expected} documents read` },
    )
    .toBe(true)
  return tree as Tree
}

async function listDocs(page: Page, projectId: string): Promise<Doc[]> {
  const out: Doc[] = []
  for (let offset = 0; ; offset += 500) {
    const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents?limit=500&offset=${offset}`)
    expect(res.ok()).toBeTruthy()
    const body = (await res.json()) as { items: Doc[]; total: number }
    out.push(...body.items)
    if (out.length >= body.total) return out
  }
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await loginViaKeycloak(page, user, pass)
  return page
}

const byPath = <T extends { name?: string; original_filename?: string; archive_path?: string | null; path?: string | null }>(items: T[], name: string): T => {
  const d = items.find((x) => (x.archive_path ?? x.path ?? x.original_filename ?? x.name) === name || x.name === name || x.original_filename === name)
  if (!d) throw new Error(`no document ${name} in ${items.map((x) => x.archive_path ?? x.path ?? x.original_filename ?? x.name).join(', ')}`)
  return d
}

test('tender pack: drop -> AI routes the confident ones -> drawings ready -> BOQ wizard pre-filled -> addendum revision + settlement flag', async ({ browser }) => {
  test.setTimeout(900_000)
  const salt = `e2e${Date.now()}`
  const pack = writePack(salt)
  expect(pack.files).toHaveLength(PACK_FILES)

  // ---- a fresh project, a draft settlement, members
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const code = `TND-${Date.now().toString(36).toUpperCase()}`
  const created = await lead.request.post('/api/v1/projects', { headers: await csrfHeaders(lead), data: { code, name: `Tender intake e2e ${salt}` } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const projectId = ((await created.json()) as { id: string }).id
  const draft = await lead.request.post(`/api/v1/projects/${projectId}/bid-settlements`, { headers: await csrfHeaders(lead) })
  expect(draft.ok(), await draft.text()).toBeTruthy()
  const settlementId = ((await draft.json()) as { id: string }).id
  await ensureProjectMember(browser, projectId, 'estimator1')

  // ---- 1. drop the pack on the empty project
  await lead.goto(`/projects/${projectId}`)
  await expect(lead.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeVisible()
  // Whichever of two identical files arrives first is the original: send the copy last.
  const uploadOrder = [...pack.files.filter((f) => !f.includes('(copy)')), ...pack.files.filter((f) => f.includes('(copy)'))]
  await lead.getByTestId('tender-file-input').setInputFiles(uploadOrder.map((f) => join(pack.dir, f)))
  await expect(lead.getByRole('list', { name: 'Files to upload' }).getByRole('listitem')).toHaveCount(PACK_FILES)
  await lead.getByRole('button', { name: `Upload ${PACK_FILES} files` }).click()

  // ---- 2. the worker reads everything (the zip expands to 4 more documents); the AI's confident answers are routed
  const tree = await waitForRead(lead, projectId, SHOWN_DOCS)
  const want: Record<string, string> = {
    'C-101 Rev A.dxf': 'drawing', 'C-101 Rev B.dxf': 'drawing', 'A-201 Rev A.dxf': 'drawing', 'S-201 Rev B.pdf': 'drawing',
    'M-301 Rev A.pdf': 'drawing', 'BOQ_Rev0.xlsx': 'boq', 'ADD-01.pdf': 'addendum', 'SPEC_Section_03300_Concrete.pdf': 'specification',
    'Conditions_of_Contract.pdf': 'contract', 'ITT.pdf': 'tender_instructions', 'Programme.xlsx': 'programme',
    'RFI_Response_07.pdf': 'clarification', 'Drawings/S-201 Rev A.pdf': 'drawing', 'Forms/Form_of_Tender.pdf': 'tender_forms',
    'Correspondence/Letter_from_Client.pdf': 'correspondence', 'Geotech/Geotechnical_Report.pdf': 'site_investigation',
  }
  for (const [name, cls] of Object.entries(want)) {
    const item = byPath(tree.items, name)
    expect([name, item.doc_class, item.decided_by, item.auto_accepted]).toEqual([name, cls, 'ai', true])
    expect(item.routed_kind, name).not.toBeNull()
  }
  const docs = await listDocs(lead, projectId)
  for (const name of Object.keys(want)) expect([name, byPath(docs, name).status]).toEqual([name, 'routed'])
  expect(byPath(docs, 'BOQ_macro.xlsm')).toMatchObject({ status: 'rejected', safety_status: 'rejected_macro' })
  expect(byPath(docs, 'bomb.zip')).toMatchObject({ status: 'rejected', safety_status: 'rejected_zip_bomb' })
  expect(byPath(docs, 'Transmittal_2.zip').status).toBe('archive')
  expect(byPath(tree.items, 'BOQ_macro.xlsm')).toMatchObject({ display_status: 'failed' })
  const copy = byPath(docs, 'C-101 Rev A (copy).dxf')
  expect(copy.flags).toContain('duplicate')
  expect(copy).toMatchObject({ status: 'routed', routed_kind: 'duplicate' }) // the copy reuses its original's class, no second AI call
  expect(byPath(docs, 'C-101 Rev B.dxf').flags).toContain('revision_of')
  // What the AI could not settle waits under "Needs your check": an image-only scan and a csv that says nothing.
  const waiting = tree.items.filter((i) => i.display_status === 'needs_check').map((i) => i.name).sort()
  expect(waiting).toEqual(['Notes.csv', 'Scan_0042.pdf'])
  expect(byPath(tree.items, 'Scan_0042.pdf').flags).toEqual(expect.arrayContaining(['not_measurable', 'low_confidence']))

  await lead.reload()
  await expect(lead.getByRole('heading', { name: 'Needs your check' })).toBeVisible()
  await expect(lead.getByRole('button', { name: 'Confirm Scan_0042.pdf' })).toBeVisible()
  await expect(lead.getByRole('button', { name: 'Confirm Notes.csv' })).toBeVisible()
  await expect(lead.getByRole('group', { name: /^Drawing, \d+ files$/ })).toBeVisible()

  // ---- 3. estimators can drop files and see the list, but cannot confirm or change anything
  const estimator = await login(browser, 'estimator1', 'Estimator1Pass!')
  await estimator.goto(`/projects/${projectId}`)
  await expect(estimator.getByRole('heading', { name: 'Needs your check' })).toBeVisible()
  await expect(estimator.getByRole('button', { name: 'Confirm Scan_0042.pdf' })).toHaveCount(0)
  await expect(estimator.getByRole('button', { name: /^Change class of / })).toHaveCount(0)
  await expect(estimator.getByRole('button', { name: 'Add more files' })).toBeVisible()
  await estimator.context().close()

  // ---- 4. drawings reach `ready` (routed to the takeoff pipeline on their own)
  const drawingDocs = docs.filter((d) => d.routed_kind === 'drawing')
  expect(drawingDocs.map((d) => d.archive_path ?? d.original_filename).sort()).toEqual(
    ['A-201 Rev A.dxf', 'C-101 Rev A.dxf', 'C-101 Rev B.dxf', 'Drawings/S-201 Rev A.pdf', 'M-301 Rev A.pdf', 'S-201 Rev B.pdf'],
  )
  for (const d of drawingDocs) {
    const drawingId = String(d.routed_ref.drawing_id)
    await expect
      .poll(async () => ((await (await lead.request.get(`/api/v1/drawings/${drawingId}`)).json()) as { status: string }).status, {
        message: `drawing for ${d.original_filename}`,
        timeout: 300_000,
        intervals: [3_000],
      })
      .toBe('ready')
  }

  // ---- 5. the BOQ wizard opens pre-filled from Next steps; the user still runs the dry run, then commits
  await lead.goto(`/projects/${projectId}`)
  await expect(lead.getByText('BOQ_Rev0.xlsx is ready to import.')).toBeVisible()
  await lead.getByRole('link', { name: 'Import BOQ' }).click()
  await expect(lead).toHaveURL(new RegExp(`/projects/${projectId}/boq/import\\?document=`))
  await expect(lead.getByRole('status').filter({ hasText: 'Pre-filled from tender document BOQ_Rev0.xlsx' })).toBeVisible({ timeout: 30_000 })
  await expect(lead.getByLabel('Item No column *')).toHaveValue('Item No')
  await expect(lead.getByLabel('Description column *')).toHaveValue('Description')
  await expect(lead.getByLabel('Quantity column')).toHaveValue('Qty')
  await expect(lead.getByLabel('Header row')).toHaveValue('3')
  await expect(lead.getByLabel('Rate column')).toHaveValue('E')
  await expect(lead.getByLabel('Sheet')).toHaveValue('BOQ')
  await expect(lead.getByRole('button', { name: 'Commit' })).toBeDisabled() // nothing was auto-run
  await lead.getByRole('button', { name: 'Preview' }).click()
  await expect(lead.getByRole('button', { name: 'Commit' })).toBeEnabled({ timeout: 30_000 })
  await lead.getByRole('button', { name: 'Commit' }).click()
  await expect(lead).toHaveURL(new RegExp(`/projects/${projectId}/boq$`), { timeout: 30_000 })
  const boqItems = (await (await lead.request.get(`/api/v1/projects/${projectId}/boq-items`)).json()) as { item_no: string }[]
  expect(boqItems.map((i) => i.item_no).sort()).toEqual(expect.arrayContaining(['1', '1.1']))

  // ---- 6. the addendum: register row, links resolved, a new drawing revision, the draft settlement flagged
  const addendumDoc = byPath(docs, 'ADD-01.pdf')
  expect(addendumDoc.routed_kind).toBe('addendum')
  const addenda = (await (await lead.request.get(`/api/v1/projects/${projectId}/addenda`)).json()) as {
    id: string; document_id: string; addendum_no: string; open_settlement_ids: string[]
    links: { reference_text: string; action: string; resolved: boolean; target_document_id: string | null }[]
  }[]
  expect(addenda).toHaveLength(1)
  const addendum = addenda[0]
  expect(addendum.addendum_no).toBe('1')
  const revA = byPath(docs, 'C-101 Rev A.dxf')
  const revB = byPath(docs, 'C-101 Rev B.dxf')
  expect(addendum.links).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ reference_text: 'C-101 Rev A', action: 'supersedes', resolved: true, target_document_id: revA.id }),
      expect.objectContaining({ reference_text: 'BOQ', action: 'amends', resolved: true }),
    ]),
  )
  // Rev B is the new revision of the drawing: a second Drawing row that supersedes Rev A's (the old one stays readable).
  const refreshed = await listDocs(lead, projectId)
  expect(byPath(refreshed, 'C-101 Rev B.dxf').supersedes_id).toBe(revA.id)
  expect(byPath(refreshed, 'C-101 Rev A.dxf').routed_ref.superseded_by).toBe(revB.id)
  expect(revA.routed_ref.drawing_id).not.toBe(revB.routed_ref.drawing_id)
  expect((await lead.request.get(`/api/v1/drawings/${revA.routed_ref.drawing_id}`)).ok()).toBeTruthy()
  expect(byPath(refreshed, 'Drawings/S-201 Rev A.pdf').routed_ref.superseded_by).toBe(byPath(refreshed, 'S-201 Rev B.pdf').id)
  expect(addendum.open_settlement_ids).toEqual([settlementId])

  await lead.goto(`/projects/${projectId}/settlement`)
  const banner = lead.getByRole('status').filter({ hasText: 'Addendum 1 changed the tender documents after this settlement was built.' })
  await expect(banner).toBeVisible({ timeout: 30_000 })
  await expect(banner).toContainText('Refresh quantities before you submit.')
  await banner.getByRole('link', { name: 'View addenda' }).click()
  await expect(lead).toHaveURL(new RegExp(`/projects/${projectId}$`))

  // ---- 7. the registers sit under "Registers": the addenda register, and the project document register (searchable, downloadable)
  await lead.getByRole('button', { name: /Registers/ }).click()
  const addendaTable = lead.getByRole('table', { name: 'Addenda register' })
  await expect(addendaTable).toBeVisible()
  await expect(addendaTable).toContainText('C-101 Rev A')
  const register = lead.getByRole('table', { name: 'Project document register' })
  await expect(register).toBeVisible()
  await expect(register.getByRole('row', { name: /SPEC_Section_03300_Concrete\.pdf/ })).toBeVisible()
  const download = register.getByRole('link', { name: 'Download SPEC_Section_03300_Concrete.pdf' })
  await expect(download).toHaveAttribute('href', /\/api\/v1\/tender-documents\/.+\/download$/)
  const file = await lead.request.get((await download.getAttribute('href'))!, { maxRedirects: 5 })
  expect(file.ok()).toBeTruthy()
  expect((await file.body()).subarray(0, 5).toString()).toBe('%PDF-')

  // ---- 8. the ones left for a person: the scan is confirmed as it is (a not-measurable drawing), the csv is filed by changing its class
  await lead.getByRole('button', { name: 'Confirm Scan_0042.pdf' }).click()
  await expect
    .poll(async () => byPath((await getTree(lead, projectId)).items, 'Scan_0042.pdf').display_status, { timeout: 60_000 })
    .not.toBe('needs_check')
  const scan = byPath(await listDocs(lead, projectId), 'Scan_0042.pdf')
  expect(scan).toMatchObject({ status: 'routed', routed_kind: 'drawing' })
  expect(scan.routed_ref.not_measurable).toBe(true)
  await lead.getByRole('button', { name: 'Change class of Notes.csv' }).first().click()
  await lead.locator('li').filter({ hasText: 'Notes.csv' }).first().getByLabel('Class', { exact: true }).selectOption({ label: 'Correspondence' })
  await expect(lead.getByRole('button', { name: 'Confirm Notes.csv' })).toHaveCount(0, { timeout: 30_000 })
  expect(byPath(await listDocs(lead, projectId), 'Notes.csv')).toMatchObject({ doc_class: 'correspondence', status: 'routed', classified_by: 'user' })
  await expect(lead.getByRole('heading', { name: 'Needs your check' })).toHaveCount(0)

  // ---- 9. the pre-filled wizard is accessible too
  const boqDoc = byPath(await listDocs(lead, projectId), 'BOQ_Rev0.xlsx')
  await lead.goto(`/projects/${projectId}/boq/import?document=${boqDoc.id}`)
  await expect(lead.getByRole('status').filter({ hasText: 'Pre-filled from tender document' })).toBeVisible({ timeout: 30_000 })
  const wizardAxe = await new AxeBuilder({ page: lead }).analyze()
  const wizardSerious = wizardAxe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(wizardSerious, JSON.stringify(wizardSerious.map((v) => v.id))).toEqual([])
  await lead.context().close()
})

test('admin can rename, disable and restore a tender class', async ({ browser }) => {
  test.setTimeout(240_000)
  const md = await login(browser, 'md1', 'Md1Pass!')
  // Start from the defaults whatever an earlier (possibly failed) run left behind.
  const reset = await md.request.patch('/api/v1/tender-classes/other', { headers: await csrfHeaders(md), data: { label: 'Other', enabled: true } })
  expect(reset.ok()).toBeTruthy()
  await md.goto('/admin')
  await md.getByRole('button', { name: 'Tender classes' }).click()
  const table = md.getByRole('table', { name: 'Tender document classes' })
  await expect(table).toBeVisible()
  await expect(table.getByRole('row')).toHaveCount(13) // header + 12 default classes

  const label = md.getByRole('textbox', { name: 'Label for other' })
  await label.fill('Miscellaneous')
  await md.getByRole('button', { name: 'Save label for other' }).click()
  await expect(md.getByRole('textbox', { name: 'Label for other' })).toHaveValue('Miscellaneous')
  await expect
    .poll(async () => ((await (await md.request.get('/api/v1/tender-classes')).json()) as { code: string; label: string }[]).find((c) => c.code === 'other')?.label)
    .toBe('Miscellaneous')

  // Disable it (a document proposed as this class can then not be confirmed until reclassified: covered by the integration tests).
  await md.getByLabel('Enable other').click()
  await expect.poll(async () => ((await (await md.request.get('/api/v1/tender-classes')).json()) as { code: string; enabled: boolean }[]).find((c) => c.code === 'other')?.enabled).toBe(false)

  // Restore the defaults so the shared tenant is left as found.
  await md.getByLabel('Enable other').click()
  await md.getByRole('button', { name: 'Reset label for other' }).click()
  await expect.poll(async () => ((await (await md.request.get('/api/v1/tender-classes')).json()) as { code: string; label: string; enabled: boolean }[]).find((c) => c.code === 'other')).toMatchObject({ label: 'Other', enabled: true })
  await md.context().close()
})

test('the managing director changes the auto-accept threshold on the AI admin screen, and only the MD can', async ({ browser }) => {
  test.setTimeout(240_000)
  const md = await login(browser, 'md1', 'Md1Pass!')
  const headers = await csrfHeaders(md)
  const put = (v: number) => md.request.put('/api/v1/admin/intake-settings', { headers, data: { auto_accept_min: v } })
  expect((await put(0.85)).ok()).toBeTruthy() // start from the default
  await md.goto('/admin')
  await md.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(md.getByText('Tender intake: automatic acceptance')).toBeVisible()
  const field = md.getByLabel('Auto-accept at or above (%)')
  await expect(field).toHaveValue('85')
  await field.fill('92')
  await md.getByRole('button', { name: 'Save' }).last().click()
  await expect(md.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
  await expect
    .poll(async () => ((await (await md.request.get('/api/v1/tender-intake/settings')).json()) as { auto_accept_min: number }).auto_accept_min)
    .toBeCloseTo(0.92)
  await field.fill('40')
  await expect(md.getByText('Enter a whole number from 50 to 100.')).toBeVisible()
  expect((await put(0.85)).ok()).toBeTruthy() // leave it as found
  await md.context().close()

  const bd = await login(browser, 'bd1', 'Bd1Pass!')
  const denied = await bd.request.put('/api/v1/admin/intake-settings', { headers: await csrfHeaders(bd), data: { auto_accept_min: 0.6 } })
  expect(denied.status()).toBe(403)
  await bd.context().close()
})

test('a 300+ file tender pack stays usable: read in batches with live progress, grouped, paged, bulk-changeable', async ({ browser }) => {
  test.setTimeout(900_000)
  const salt = `bulk${Date.now()}`
  const pack = writePack(salt, 320)
  const total = pack.files.length
  expect(total).toBe(PACK_FILES + 320)
  const shown = total - 1 + 4 // the zip itself is not listed; its four members are

  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const created = await lead.request.post('/api/v1/projects', {
    headers: await csrfHeaders(lead),
    data: { code: `TNB-${Date.now().toString(36).toUpperCase()}`, name: `Tender intake bulk ${salt}` },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const projectId = ((await created.json()) as { id: string }).id

  await lead.goto(`/projects/${projectId}`)
  await lead.getByTestId('tender-file-input').setInputFiles(pack.files.map((f) => join(pack.dir, f)))
  await lead.getByRole('button', { name: `Upload ${total} files` }).click()
  // Live progress while the pack is read (or the unpacking note just before the first count).
  await expect(lead.getByRole('status').filter({ hasText: /Reading documents: \d+ of \d+|Unpacking your upload/ })).toBeVisible({ timeout: 120_000 })

  const tree = await waitForRead(lead, projectId, shown, 600_000)
  expect(tree.summary.total).toBe(shown)
  expect(tree.items.filter((i) => i.display_status === 'failed' && i.status === 'failed')).toEqual([])
  // Every confident file was routed by the AI on its own; only what it could not settle waits.
  expect(tree.items.filter((i) => i.auto_accepted).length).toBeGreaterThanOrEqual(320)
  expect(tree.summary.needs_check).toBeLessThanOrEqual(3)
  await lead.reload()
  await expect(lead.getByText(new RegExp(`^${shown} files$`))).toBeVisible({ timeout: 60_000 })

  // Grouped by class with counts (the four bulk kinds are 80 files each).
  for (const [label, n] of [['Specification', 80], ['Clarification / RFI response', 80], ['Tender instructions', 80], ['Correspondence', 80]] as const) {
    await expect(lead.getByRole('group', { name: new RegExp(`^${label.replace('/', '\\/')}, (\\d+) files$`) }).first()).toBeVisible()
    const group = tree.summary.by_class
    expect(Object.values(group).reduce((a, b) => a + b, 0)).toBe(shown - tree.items.filter((i) => !i.doc_class).length)
    expect(n).toBe(80)
  }

  // "Original folders" puts the 340 loose files in one long list that shows 100 rows at a time.
  await lead.getByRole('button', { name: 'Original folders' }).click()
  const rowCount = () => lead.getByRole('list', { name: 'Top level (no folder) files' }).getByRole('listitem').count()
  await expect.poll(rowCount, { timeout: 30_000 }).toBe(100)
  await lead.getByRole('button', { name: /^Show 100 more/ }).click()
  await expect.poll(rowCount).toBe(200)
  await lead.getByRole('button', { name: 'By document type' }).click()

  // Search narrows a 340-row pack to a handful.
  await lead.getByLabel('Search documents').fill('Bulk_RFI_0002')
  await expect(lead.getByText(`1 of ${shown} files match`)).toBeVisible()
  await lead.getByRole('button', { name: 'Clear filters' }).click()

  // Select a whole group and change its class in one go: each file is re-routed under the new class.
  const specs = lead.getByRole('group', { name: /^Specification, \d+ files$/ }).first()
  const specCount = Number(/(\d+) files/.exec((await specs.getAttribute('aria-label')) ?? '')?.[1])
  expect(specCount).toBeGreaterThanOrEqual(80)
  await lead.getByLabel(new RegExp(`^Select all ${specCount} in Specification$`)).check()
  await lead.getByRole('button', { name: new RegExp(`^Change class for ${specCount} files$`) }).click()
  const dialog = lead.getByRole('dialog', { name: 'Change class' })
  await dialog.getByLabel('Class', { exact: true }).selectOption({ label: 'Programme / schedule' })
  await dialog.getByRole('button', { name: 'Apply class' }).click()
  await expect(lead.getByRole('status').filter({ hasText: new RegExp(`Changed ${specCount}, failed 0`) })).toBeVisible({ timeout: 300_000 })
  const after = await getTree(lead, projectId)
  expect(after.summary.by_class.specification ?? 0).toBe(0)
  expect(after.summary.by_class.programme).toBeGreaterThanOrEqual(specCount)
  expect(after.items.filter((i) => i.doc_class === 'programme').every((i) => i.routed_kind === 'register')).toBe(true)
  await lead.context().close()
})
