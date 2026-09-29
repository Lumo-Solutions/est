import { execFileSync } from 'node:child_process'
import { mkdtempSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, ensureProjectMember, loginViaKeycloak } from './helpers'

// Tender document intake, real backend, real Keycloak, real Celery workers, real S3, no mocks.
// A fresh project per run (so nothing is a duplicate of an earlier run and the shared D1-SIM
// fixture is untouched) and a per-run salted copy of the synthetic pack
// (backend/app/intake/sample_pack.py, written by `python -m app.cli write-tender-pack`).

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
}

const PACK_FILES = 18 // top-level files in the pack; the zip adds 4 more documents

function writePack(salt: string, extra = 0): { dir: string; files: string[] } {
  const remote = `/tmp/pack-${salt}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'write-tender-pack', '--out', remote, '--salt', salt, '--extra', String(extra)], { stdio: 'pipe' })
  const dir = mkdtempSync(join(tmpdir(), 'tender-pack-'))
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  return { dir, files: readdirSync(dir).sort() }
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

async function waitForClassification(page: Page, projectId: string, expected: number): Promise<Doc[]> {
  let docs: Doc[] = []
  await expect
    .poll(
      async () => {
        docs = await listDocs(page, projectId)
        return docs.length >= expected && docs.every((d) => !['received', 'processing'].includes(d.status))
      },
      { timeout: 180_000, intervals: [2_000] },
    )
    .toBe(true)
  return docs
}

// Distinct data rows AG Grid currently has in the DOM (a row can appear in both the pinned and the
// centre container, so count by row-id rather than by element).
const renderedRows = (page: Page) =>
  page.evaluate(() => new Set([...document.querySelectorAll('[role="row"][row-id]')].map((e) => e.getAttribute('row-id'))).size)

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await loginViaKeycloak(page, user, pass)
  return page
}

const byName = (docs: Doc[], name: string) => {
  const d = docs.find((x) => (x.archive_path ?? x.original_filename) === name)
  if (!d) throw new Error(`no document ${name} in ${docs.map((x) => x.archive_path ?? x.original_filename).join(', ')}`)
  return d
}

test('tender pack: drop -> proposals -> bulk-confirm -> drawings ready -> BOQ wizard pre-filled -> addendum revision + settlement flag', async ({ browser }) => {
  test.setTimeout(600_000)
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

  // ---- 1. drop the pack
  await lead.goto(`/projects/${projectId}?tab=tender-documents`)
  await expect(lead.getByRole('heading', { name: 'Upload tender documents' })).toBeVisible()
  // Whichever of two identical files arrives first is the original: send the copy last.
  const uploadOrder = [...pack.files.filter((f) => !f.includes('(copy)')), ...pack.files.filter((f) => f.includes('(copy)'))]
  await lead.getByTestId('tender-file-input').setInputFiles(uploadOrder.map((f) => join(pack.dir, f)))
  await expect(lead.getByRole('list', { name: 'Files to upload' }).getByRole('listitem')).toHaveCount(PACK_FILES)
  await lead.getByRole('button', { name: `Upload ${PACK_FILES} files` }).click()
  await expect(lead.getByRole('status').filter({ hasText: `Uploaded ${PACK_FILES} of ${PACK_FILES} files` })).toBeVisible({ timeout: 60_000 })

  // ---- 2. proposals: the worker classifies everything (the zip expands to 4 more documents)
  const docs = await waitForClassification(lead, projectId, PACK_FILES + 4)
  const want: Record<string, string> = {
    'C-101 Rev A.dxf': 'drawing', 'C-101 Rev B.dxf': 'drawing', 'A-201 Rev A.dxf': 'drawing', 'S-201 Rev B.pdf': 'drawing',
    'M-301 Rev A.pdf': 'drawing', 'BOQ_Rev0.xlsx': 'boq', 'ADD-01.pdf': 'addendum', 'SPEC_Section_03300_Concrete.pdf': 'specification',
    'Conditions_of_Contract.pdf': 'contract', 'ITT.pdf': 'tender_instructions', 'Programme.xlsx': 'programme',
    'RFI_Response_07.pdf': 'clarification', 'Drawings/S-201 Rev A.pdf': 'drawing', 'Forms/Form_of_Tender.pdf': 'tender_forms',
    'Correspondence/Letter_from_Client.pdf': 'correspondence', 'Geotech/Geotechnical_Report.pdf': 'site_investigation',
  }
  for (const [name, cls] of Object.entries(want)) {
    const d = byName(docs, name)
    expect([name, d.status, d.doc_class]).toEqual([name, 'proposed', cls])
  }
  expect(byName(docs, 'BOQ_macro.xlsm')).toMatchObject({ status: 'rejected', safety_status: 'rejected_macro' })
  expect(byName(docs, 'bomb.zip')).toMatchObject({ status: 'rejected', safety_status: 'rejected_zip_bomb' })
  expect(byName(docs, 'Transmittal_2.zip').status).toBe('archive')
  expect(byName(docs, 'C-101 Rev A (copy).dxf').flags).toContain('duplicate')
  expect(byName(docs, 'Scan_0042.pdf').flags).toEqual(expect.arrayContaining(['not_measurable', 'low_confidence']))
  expect(byName(docs, 'C-101 Rev B.dxf').flags).toContain('revision_of')

  // The proposals are visible in the review grid (search brings rows into the virtualised view).
  await lead.reload()
  await lead.getByLabel('Search documents').fill('C-101')
  const rowA = lead.getByRole('row', { name: /C-101 Rev A\.dxf/ }).first()
  await expect(rowA).toBeVisible()
  await expect(rowA).toContainText('Drawing')
  await expect(rowA).toContainText('98%')
  await expect(rowA).toContainText('proposed')
  await expect(lead.getByRole('row', { name: /C-101 Rev A \(copy\)\.dxf/ })).toContainText('Duplicate')
  await lead.getByLabel('Search documents').fill('')

  // ---- 3. estimators can drop files but cannot confirm anything
  const estimator = await login(browser, 'estimator1', 'Estimator1Pass!')
  await estimator.goto(`/projects/${projectId}?tab=tender-documents`)
  await expect(estimator.getByRole('heading', { name: 'Upload tender documents' })).toBeVisible()
  await estimator.getByLabel('Search documents').fill('C-101')
  await expect(estimator.getByRole('row', { name: /C-101 Rev A\.dxf/ }).first()).toBeVisible()
  await expect(estimator.getByRole('button', { name: 'Confirm high-confidence' })).toHaveCount(0)
  await expect(estimator.getByRole('button', { name: /^Confirm C-101/ })).toHaveCount(0)
  await estimator.context().close()

  // ---- 4. bulk-confirm the high-confidence proposals
  await lead.getByRole('button', { name: 'Confirm high-confidence' }).click()
  await lead.getByRole('button', { name: 'Confirm all' }).click()
  const summary = lead.getByRole('status').filter({ hasText: /Confirmed \d+, skipped \d+, failed 0/ })
  await expect(summary).toBeVisible({ timeout: 60_000 })
  const confirmed = Number(/Confirmed (\d+)/.exec((await summary.textContent()) ?? '')?.[1])
  expect(confirmed).toBeGreaterThanOrEqual(13)

  const after = await listDocs(lead, projectId)
  // What bulk-confirm leaves for a human: the scan, the notes file and the duplicate.
  expect(after.filter((d) => d.status === 'proposed').map((d) => d.archive_path ?? d.original_filename).sort()).toEqual(
    ['C-101 Rev A (copy).dxf', 'Notes.csv', 'Scan_0042.pdf'],
  )

  // ---- 5. drawings reach `ready`
  const drawingDocs = after.filter((d) => d.routed_kind === 'drawing')
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

  // ---- 6. the BOQ wizard opens pre-filled; the user still runs the dry run, then commits
  await lead.goto(`/projects/${projectId}?tab=tender-documents`)
  await lead.getByLabel('Search documents').fill('BOQ_Rev0')
  const boqRow = lead.getByRole('row', { name: /BOQ_Rev0\.xlsx/ }).first()
  await expect(boqRow).toContainText('routed')
  await boqRow.getByRole('link', { name: 'Open BOQ_Rev0.xlsx in BOQ import wizard' }).click()
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

  // ---- 7. the addendum: register row, links resolved, a new drawing revision, the draft settlement flagged
  const addendumDoc = byName(after, 'ADD-01.pdf')
  expect(addendumDoc.routed_kind).toBe('addendum')
  const addenda = (await (await lead.request.get(`/api/v1/projects/${projectId}/addenda`)).json()) as {
    id: string; document_id: string; addendum_no: string; open_settlement_ids: string[]
    links: { reference_text: string; action: string; resolved: boolean; target_document_id: string | null }[]
  }[]
  expect(addenda).toHaveLength(1)
  const addendum = addenda[0]
  expect(addendum.addendum_no).toBe('1')
  const revA = byName(after, 'C-101 Rev A.dxf')
  const revB = byName(after, 'C-101 Rev B.dxf')
  expect(addendum.links).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ reference_text: 'C-101 Rev A', action: 'supersedes', resolved: true, target_document_id: revA.id }),
      expect.objectContaining({ reference_text: 'BOQ', action: 'amends', resolved: true }),
    ]),
  )
  // Rev B is the new revision of the drawing: a second Drawing row that supersedes Rev A's (the old one stays readable).
  expect(revB.supersedes_id).toBe(revA.id)
  expect(revA.routed_ref.superseded_by).toBe(revB.id)
  expect(revA.routed_ref.drawing_id).not.toBe(revB.routed_ref.drawing_id)
  expect((await lead.request.get(`/api/v1/drawings/${revA.routed_ref.drawing_id}`)).ok()).toBeTruthy()
  expect(byName(after, 'Drawings/S-201 Rev A.pdf').routed_ref.superseded_by).toBe(byName(after, 'S-201 Rev B.pdf').id)
  expect(addendum.open_settlement_ids).toEqual([settlementId])

  await lead.goto(`/projects/${projectId}/settlement`)
  const banner = lead.getByRole('status').filter({ hasText: 'Addendum 1 changed the tender documents after this settlement was built.' })
  await expect(banner).toBeVisible({ timeout: 30_000 })
  await expect(banner).toContainText('Refresh quantities before you submit.')
  await banner.getByRole('link', { name: 'View addenda' }).click()
  await expect(lead).toHaveURL(new RegExp(`/projects/${projectId}\\?tab=tender-documents`))
  const addendaTable = lead.getByRole('table', { name: 'Addenda register' })
  await expect(addendaTable).toBeVisible()
  await expect(addendaTable).toContainText('C-101 Rev A')

  // ---- 8. the rest lands in the project document register: searchable and downloadable
  const register = lead.getByRole('table', { name: 'Project document register' })
  await expect(register).toBeVisible()
  await expect(register.getByRole('row', { name: /SPEC_Section_03300_Concrete\.pdf/ })).toBeVisible()
  const download = register.getByRole('link', { name: 'Download SPEC_Section_03300_Concrete.pdf' })
  await expect(download).toHaveAttribute('href', /\/api\/v1\/tender-documents\/.+\/download$/)
  const file = await lead.request.get((await download.getAttribute('href'))!, { maxRedirects: 5 })
  expect(file.ok()).toBeTruthy()
  expect((await file.body()).subarray(0, 5).toString()).toBe('%PDF-')

  // ---- 9. the ones bulk-confirm left are reviewed one by one: the scan is a not-measurable drawing
  await lead.getByLabel('Search documents').fill('Scan_0042')
  await expect(lead.getByRole('row', { name: /Scan_0042\.pdf/ }).first()).toContainText('Not measurable')
  await lead.getByRole('button', { name: 'Confirm Scan_0042.pdf' }).click()
  await expect(lead.getByRole('row', { name: /Scan_0042\.pdf/ }).first()).toContainText('routed', { timeout: 30_000 })
  const scan = byName(await listDocs(lead, projectId), 'Scan_0042.pdf')
  expect(scan).toMatchObject({ status: 'routed', routed_kind: 'drawing' })
  expect(scan.routed_ref.not_measurable).toBe(true)

  // ---- 10. accessibility and layout of the finished tab, and of the pre-filled wizard
  await lead.getByLabel('Search documents').fill('')
  await lead.waitForLoadState('networkidle')
  for (const width of [1440, 1280, 1024]) {
    await lead.setViewportSize({ width, height: 900 })
    await lead.goto(`/projects/${projectId}?tab=tender-documents`)
    await expect(lead.getByRole('table', { name: 'Project document register' })).toBeVisible()
    await lead.waitForTimeout(500)
    const { scrollWidth, clientWidth } = await lead.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }))
    expect(scrollWidth, `tender tab overflows sideways at ${width}px`).toBeLessThanOrEqual(clientWidth + 1)
    await lead.screenshot({ path: `../docs/ui-qa/screenshots/tender-intake/tender-tab-${width}.png` })
  }
  const axe = await new AxeBuilder({ page: lead }).analyze()
  const serious = axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })), null, 2)).toEqual([])

  const boqDoc = byName(await listDocs(lead, projectId), 'BOQ_Rev0.xlsx')
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

test('a 300+ file tender pack stays usable: paged, virtualised, bulk-confirmable', async ({ browser }) => {
  test.setTimeout(600_000)
  const salt = `bulk${Date.now()}`
  const pack = writePack(salt, 320)
  const total = pack.files.length
  expect(total).toBe(PACK_FILES + 320)

  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const created = await lead.request.post('/api/v1/projects', {
    headers: await csrfHeaders(lead),
    data: { code: `TNB-${Date.now().toString(36).toUpperCase()}`, name: `Tender intake bulk ${salt}` },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const projectId = ((await created.json()) as { id: string }).id

  await lead.goto(`/projects/${projectId}?tab=tender-documents`)
  await lead.getByTestId('tender-file-input').setInputFiles(pack.files.map((f) => join(pack.dir, f)))
  await lead.getByRole('button', { name: `Upload ${total} files` }).click()
  await expect(lead.getByRole('status').filter({ hasText: `Uploaded ${total} of ${total} files` })).toBeVisible({ timeout: 300_000 })

  const docs = await waitForClassification(lead, projectId, total + 4)
  expect(docs.filter((d) => d.status === 'proposed').length).toBeGreaterThanOrEqual(320)
  expect(docs.filter((d) => d.status === 'failed')).toEqual([])

  // Paged server-side (100 a page) and virtualised: never 100+ DOM rows at once.
  await lead.reload()
  const shown = lead.getByText(/^Showing 1 to 100 of \d+$/)
  await expect(shown).toBeVisible({ timeout: 60_000 })
  expect(Number(/of (\d+)/.exec((await shown.textContent()) ?? '')?.[1])).toBe(docs.length)
  await expect.poll(() => renderedRows(lead), { timeout: 30_000 }).toBeGreaterThan(5)
  const rendered = await renderedRows(lead)
  expect(rendered).toBeLessThan(60)
  const scrolled = Date.now()
  await lead.getByRole('grid').first().hover()
  await lead.mouse.wheel(0, 100_000)
  await expect(lead.getByRole('row', { name: /Bulk_/ }).last()).toBeVisible()
  expect(Date.now() - scrolled).toBeLessThan(5_000)
  expect(await renderedRows(lead)).toBeLessThan(60)

  await lead.getByRole('navigation', { name: 'Pagination' }).first().getByRole('button', { name: 'Page 4' }).click()
  await expect(lead.getByText(new RegExp(`^Showing 301 to ${docs.length} of ${docs.length}$`))).toBeVisible()
  await lead.getByRole('navigation', { name: 'Pagination' }).first().getByRole('button', { name: 'Page 1' }).click()

  // Search narrows a 340-row pack to a handful.
  await lead.getByLabel('Search documents').fill('Bulk_RFI_0002')
  await expect(lead.getByRole('row', { name: /Bulk_RFI_0002\.pdf/ }).first()).toBeVisible()
  await expect(lead.getByText(/^Showing 1 to 1 of 1$/)).toBeVisible()
  await lead.getByLabel('Search documents').fill('')

  // One click confirms every confident proposal in the pack.
  await lead.getByRole('button', { name: 'Confirm high-confidence' }).click()
  await lead.getByRole('button', { name: 'Confirm all' }).click()
  const summary = lead.getByRole('status').filter({ hasText: /Confirmed \d+, skipped \d+, failed 0/ })
  await expect(summary).toBeVisible({ timeout: 300_000 })
  expect(Number(/Confirmed (\d+)/.exec((await summary.textContent()) ?? '')?.[1])).toBeGreaterThanOrEqual(330)
  const routed = (await listDocs(lead, projectId)).filter((d) => d.status === 'routed')
  expect(routed.length).toBeGreaterThanOrEqual(330)

  // The register pages too (50 a page).
  await expect(lead.getByRole('table', { name: 'Project document register' })).toBeVisible()
  await expect(lead.getByText(/^Showing 1 to 50 of \d+$/)).toBeVisible()
  await lead.context().close()
})
