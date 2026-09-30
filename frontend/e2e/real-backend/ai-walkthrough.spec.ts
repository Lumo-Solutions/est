import { execFileSync } from 'node:child_process'
import { mkdtempSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak, resolveUnresolvedLines } from './helpers'

// The whole AI feature set, real backend, real Keycloak, real Celery workers, real S3, the MOCK provider (no key):
//   create project -> drop the FOLDER -> classify + confirm -> import BOQ -> read drawing annotations -> verify the BOQ
//   against the drawings -> review the report + accept a mapping -> export xlsx/pdf
//   -> build the settlement -> propose costs with AI -> accept (single + bulk) -> suggest markup + set it -> submit
//   -> approve as a different user -> export.
// Preconditions (docs/ai-report.md): `make up`, `make migrate`, `make seed`, `make dev-seed-ai-demo`,
// AI_PROVIDER=mock and TAKEOFF_PERSIST_GEOMETRY=true in deploy/.env. MFA on or off both work (helpers handle it).
// Everything created is tagged (project code AI-DEMO-E2E-*) and removed by `make dev-clean-demo-data`.

const PACK_ROOT = 'Al Reem Package 3'
const EXPECTED_CLASSIFICATION: Record<string, string> = {
  'C-101 Road and Drainage Plan Rev B.dxf': 'drawing',
  'L-201 Landscape Plan Rev A.pdf': 'drawing',
  'BOQ Rev 0.xlsx': 'boq',
  'BOQ Rev 0 (print copy).pdf': 'boq',
  'Particular Specification.pdf': 'specification',
  'Addendum No 1.pdf': 'addendum',
  'Conditions of Contract.pdf': 'contract',
  'C-102 Storm Drainage Plan and Profile Rev A.pdf': 'drawing', // filed under the BOQ folder: the content decides
  'Site visit notes.pdf': 'other', // the AI cannot tell; a person files it
}
// item_no -> the class the designed pack must produce (backend/app/demo/ai_demo.py::EXPECTED_CLASSES)
const EXPECTED_CLASSES: Record<string, string> = {
  '1.1': 'match', '1.2': 'match', '1.3': 'missing_in_drawings', '2.1': 'match', '2.2': 'variance', '2.3': 'match',
  '2.4': 'missing_in_drawings', '3.1': 'match', '3.2': 'match', '3.3': 'match', '3.4': 'missing_in_drawings',
  '4.1': 'missing_in_drawings', '4.2': 'missing_in_drawings', '5.1': 'match', '5.2': 'variance', '5.3': 'match',
  '6.1': 'not_verifiable', '6.2': 'not_verifiable',
}

interface Doc {
  id: string
  original_filename: string
  archive_path: string | null
  status: string
  doc_class: string | null
  routed_kind: string | null
  routed_ref: Record<string, unknown>
}
interface VLine {
  id: string
  item_no: string | null
  vclass: string
  method: string
  mapped_by: string
  drawing_quantity: number | null
  delta_pct: number | null
  boq_line_item_id: string | null
  evidence: { ref: string; page: number | null }[]
  candidates: { ref: string; selected: boolean }[]
}

function writeAiPack(): string {
  const remote = `/tmp/ai-pack-${Date.now()}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'write-ai-demo-pack', '--out', remote], { stdio: 'pipe' })
  const dir = mkdtempSync(join(tmpdir(), 'ai-demo-pack-'))
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  return dir
}

function seedQuotes(projectCode: string): void {
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'seed-ai-demo-quotes', '--project', projectCode], { stdio: 'pipe' })
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, acceptDownloads: true })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.error(`PAGEERROR (${user}): ${e.message}\n${e.stack ?? ''}`))
  await loginViaKeycloak(page, user, pass)
  return page
}

async function listDocs(page: Page, projectId: string): Promise<Doc[]> {
  const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents?limit=500`)
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as { items: Doc[] }).items
}

async function pollJson<T>(page: Page, url: string, done: (v: T) => boolean, message: string, timeout = 240_000): Promise<T> {
  let last: T | undefined
  await expect
    .poll(
      async () => {
        const r = await page.request.get(url)
        last = (await r.json()) as T
        return done(last)
      },
      { message, timeout, intervals: [2_000] },
    )
    .toBe(true)
  return last as T
}

async function allLines(page: Page, runId: string): Promise<VLine[]> {
  const res = await page.request.get(`/api/v1/verification-runs/${runId}/lines?limit=1000`)
  expect(res.ok(), await res.text()).toBeTruthy()
  return ((await res.json()) as { items: VLine[] }).items
}

test.describe.serial('AI walkthrough (mock provider)', () => {
  test.setTimeout(900_000)
  const state: { projectId: string; code: string; runId: string; drawings: string[] } = { projectId: '', code: '', runId: '', drawings: [] }

  test('folder drop -> classify -> confirm -> BOQ import -> annotations -> verification report -> export', async ({ browser }) => {
    const pack = writeAiPack()
    const lead = await login(browser, 'lead1', 'Lead1Pass!')

    // the deployment is on the mock provider with no key: AI is "available" and never external
    const status = (await (await lead.request.get('/api/v1/ai/status')).json()) as { provider: string; external: boolean; available: boolean }
    expect(status).toMatchObject({ provider: 'mock', external: false, available: true })

    // ---- 1. create the project in the UI: it lands on the one project page with the empty state
    state.code = `AI-DEMO-E2E-${Date.now().toString(36).toUpperCase()}`
    await lead.goto('/')
    await lead.getByRole('button', { name: 'New project' }).click()
    await lead.getByLabel('Code').fill(state.code)
    await lead.getByLabel('Name').fill('Al Reem Package 3 (AI walkthrough)')
    await lead.getByRole('button', { name: 'Create project' }).click()
    await expect(lead).toHaveURL(/\/projects\/[0-9a-f-]+$/)
    state.projectId = /projects\/([0-9a-f-]+)/.exec(lead.url())![1]
    await expect(lead.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeVisible()

    // ---- 2. drop the whole FOLDER (webkitdirectory keeps the relative paths)
    await lead.getByTestId('tender-folder-input').setInputFiles(join(pack, PACK_ROOT))
    await expect(lead.getByRole('list', { name: 'Files to upload' }).getByRole('listitem')).toHaveCount(9)
    await expect(lead.getByRole('list', { name: 'Files to upload' })).toContainText('01 Drawings')
    await lead.getByRole('button', { name: 'Upload 9 files' }).click()

    // ---- 3. classification: the (mock) AI reads every file; the folder is only a hint
    let docs: Doc[] = []
    await expect
      .poll(async () => {
        docs = await listDocs(lead, state.projectId)
        return docs.length === 9 && docs.every((d) => !['received', 'processing'].includes(d.status))
      }, { timeout: 180_000, intervals: [2_000] })
      .toBe(true)
    for (const d of docs) {
      expect([d.original_filename, d.doc_class]).toEqual([d.original_filename, EXPECTED_CLASSIFICATION[d.original_filename]])
    }
    expect(docs.find((d) => d.original_filename.startsWith('C-101'))?.archive_path).toContain('01 Drawings')

    // ---- 4. the AI's confident answers were accepted and routed on their own; the one it was unsure of is filed by a person
    await lead.reload()
    await expect(lead.getByRole('heading', { name: 'Needs your check' })).toBeVisible()
    await lead.getByRole('button', { name: 'Change class of Site visit notes.pdf' }).first().click()
    await lead.getByLabel('Class').selectOption({ label: 'Correspondence' })
    await expect(lead.getByRole('button', { name: 'Confirm Site visit notes.pdf' })).toHaveCount(0, { timeout: 30_000 })
    docs = await listDocs(lead, state.projectId)
    const drawingDocs = docs.filter((d) => d.routed_kind === 'drawing')
    expect(drawingDocs).toHaveLength(3)
    for (const d of drawingDocs) {
      const drawingId = String(d.routed_ref.drawing_id)
      state.drawings.push(drawingId)
      await pollJson<{ status: string }>(lead, `/api/v1/drawings/${drawingId}`, (v) => v.status === 'ready', `drawing ${d.original_filename} ready`, 300_000)
    }

    // ---- 5. the Excel BOQ opens pre-filled in the wizard; preview (dry run) then commit
    await lead.goto(`/projects/${state.projectId}`)
    await lead.getByLabel('BOQ document').selectOption({ label: 'BOQ Rev 0.xlsx' })
    await lead.getByRole('link', { name: 'Import BOQ' }).click()
    await expect(lead.getByRole('status').filter({ hasText: /Pre-filled from tender document/ })).toBeVisible({ timeout: 30_000 })
    await lead.getByRole('button', { name: 'Preview' }).click()
    await expect(lead.getByRole('button', { name: 'Commit' })).toBeEnabled({ timeout: 30_000 })
    await lead.getByRole('button', { name: 'Commit' }).click()
    await expect(lead).toHaveURL(new RegExp(`/projects/${state.projectId}/boq$`), { timeout: 30_000 })
    const items = (await (await lead.request.get(`/api/v1/projects/${state.projectId}/boq-items`)).json()) as { item_no: string }[]
    expect(items.map((i) => i.item_no)).toEqual(expect.arrayContaining(['1', '1.1', '2.1', '5.3', '6.2']))

    // ---- 6. read the drawing annotations with the AI (per-sheet progress, links into the takeoff viewer)
    await lead.goto(`/projects/${state.projectId}/drawings/${state.drawings[0]}`)
    await lead.getByRole('button', { name: /Read annotations with AI/ }).click()
    await lead.goto(`/projects/${state.projectId}/drawings/${state.drawings[1]}`)
    await lead.getByRole('button', { name: /Read annotations with AI/ }).click()
    const summary = await pollJson<{ sheets: number; queued: number; done: number; annotations: number }>(
      lead, `/api/v1/projects/${state.projectId}/drawing-annotations/summary`, (v) => v.sheets > 0 && v.queued === 0 && v.annotations > 0, 'annotations read',
    )
    expect(summary.done).toBeGreaterThanOrEqual(2)
    expect(summary.annotations).toBeGreaterThanOrEqual(10) // 7 on C-101 + 3 on L-201, all AI-read

    // ---- 7. verify the BOQ against the drawings
    await lead.goto(`/projects/${state.projectId}/verification`)
    await lead.getByRole('button', { name: /Start verification/ }).click()
    let runId = ''
    await expect
      .poll(async () => {
        const runs = (await (await lead.request.get(`/api/v1/projects/${state.projectId}/verification-runs`)).json()) as { id: string; status: string }[]
        runId = runs[0]?.id ?? ''
        return runs[0]?.status
      }, { timeout: 240_000, intervals: [2_000] })
      .toBe('ready')
    state.runId = runId
    const lines = await allLines(lead, runId)
    const byItem = new Map(lines.filter((l) => l.item_no).map((l) => [l.item_no!, l]))
    for (const [itemNo, cls] of Object.entries(EXPECTED_CLASSES)) {
      expect([itemNo, byItem.get(itemNo)?.vclass]).toEqual([itemNo, cls])
    }
    expect(byItem.get('2.2')!.delta_pct).toBeCloseTo(50, 1)
    expect(byItem.get('5.2')!.delta_pct).toBeCloseTo(15, 1)
    expect(byItem.get('2.1')!.method).toBe('measured')
    expect(byItem.get('2.3')!.method).toBe('annotated')
    const missingInBoq = lines.filter((l) => l.vclass === 'missing_in_boq')
    expect(missingInBoq).toHaveLength(1) // the 450mm storm pipe the BOQ forgot
    expect(missingInBoq[0].drawing_quantity).toBeCloseTo(80, 1)

    // ---- 8. review in the UI: summary cards, filter, open a line, accept the AI's mapping, evidence opens the viewer
    await expect(lead.getByRole('status').or(lead.getByText('Verification report')).first()).toBeVisible()
    await expect(lead.getByRole('button', { name: /Variance/ }).first()).toBeVisible()
    await lead.getByRole('button', { name: /Variance/ }).first().click()
    const row22 = lead.getByRole('row', { name: /2\.2/ }).first()
    await expect(row22).toBeVisible()
    await row22.getByRole('button', { name: 'Open line 2.2' }).click()
    const panel = lead.getByRole('dialog', { name: /Line detail: 2\.2/ })
    await expect(panel).toContainText('150')
    await panel.getByRole('button', { name: /^Accept/ }).first().click()
    await expect
      .poll(async () => (await allLines(lead, runId)).find((l) => l.item_no === '2.2')?.mapped_by)
      .toBe('user') // confirmed by a person, and linked into the BOQ reconciliation
    const links = (await (await lead.request.get(`/api/v1/boq-items/${(await allLines(lead, runId)).find((l) => l.item_no === '2.2')!.boq_line_item_id}/measurements`)).json()) as unknown[]
    expect(links.length).toBeGreaterThanOrEqual(2) // both 150mm runs

    // ---- 9. exports (xlsx and PDF), audited
    const [xlsx] = await Promise.all([lead.waitForEvent('download'), lead.getByRole('button', { name: /Export Excel/ }).click()])
    expect(xlsx.suggestedFilename()).toMatch(/\.xlsx$/)
    const xlsxPath = join(tmpdir(), `ai-verification-${Date.now()}.xlsx`)
    await xlsx.saveAs(xlsxPath)
    expect(statSync(xlsxPath).size).toBeGreaterThan(4_000)
    const [pdf] = await Promise.all([lead.waitForEvent('download'), lead.getByRole('button', { name: /Export PDF/ }).click()])
    expect(pdf.suggestedFilename()).toMatch(/\.pdf$/)
    const pdfPath = join(tmpdir(), `ai-verification-${Date.now()}.pdf`)
    await pdf.saveAs(pdfPath)
    expect(statSync(pdfPath).size).toBeGreaterThan(2_000)

    // ---- 10. the admin usage view shows this run's AI calls (mock: no cost)
    const md = await login(browser, 'md1', 'Md1Pass!')
    const usage = (await (await md.request.get('/api/v1/admin/ai-usage')).json()) as { rows: { task: string; calls: number; cost_usd: number }[] }
    const tasks = new Set(usage.rows.map((r) => r.task))
    for (const t of ['boq_interpret', 'evidence_rank', 'drawing_annotations']) expect(tasks.has(t), `AI usage row for ${t}`).toBe(true)
    expect(usage.rows.every((r) => r.cost_usd === 0)).toBe(true)
    await md.context().close()
    await lead.context().close()
  })

  test('settlement: build -> propose costs with AI -> accept -> bulk accept -> suggest markup -> submit -> approve -> export', async ({ browser }) => {
    expect(state.projectId, 'the first test must have created the project').not.toBe('')
    seedQuotes(state.code)

    const bd = await login(browser, 'bd1', 'Bd1Pass!')
    await bd.goto(`/projects/${state.projectId}/settlement`)
    await bd.getByRole('button', { name: /^Build( new)? settlement draft$/ }).click()
    await expect(bd.getByRole('button', { name: 'Submit for approval' })).toBeVisible()

    // ---- propose costs with AI
    await bd.getByRole('button', { name: /Propose costs with AI/ }).click()
    const settlement = (await (await bd.request.get(`/api/v1/projects/${state.projectId}/bid-settlements`)).json()) as { id: string; is_current: boolean }[]
    const sid = settlement.find((s) => s.is_current)!.id
    let costRun: { id: string; status: string; counts: Record<string, number> } | undefined
    await expect
      .poll(async () => {
        costRun = ((await (await bd.request.get(`/api/v1/bid-settlements/${sid}/ai/runs`)).json()) as NonNullable<typeof costRun>[])[0]
        return costRun?.status
      }, { message: 'cost proposals ready', timeout: 240_000, intervals: [2_000] })
      .toBe('ready')
    expect(costRun!.counts.lines).toBeGreaterThanOrEqual(16)
    expect(costRun!.counts.no_source).toBeGreaterThanOrEqual(3) // lines nothing in the library or quotes covers

    const page1 = (await (await bd.request.get(`/api/v1/bid-settlements/${sid}/ai/proposals`)).json()) as {
      items: { id: string; item_no: string; status: string; chosen: { type: string; rate: number } | null; flags: string[]; confidence: number; source: string }[]
    }
    const by = new Map(page1.items.map((p) => [p.item_no, p]))
    expect(by.get('2.1')!.chosen!.type).toMatch(/quote|library/)
    expect(by.get('2.2')!.flags).toContain('quote_exclusions')     // the vendor excluded testing
    expect(by.get('4.1')!.flags).toContain('vendor_not_eligible')  // the vendor whose prequalification lapsed
    expect(by.get('2.4')!.chosen).toBeNull()                       // nothing covers a connection to an existing manhole
    expect(by.get('1.1')!.chosen!.rate).toBeCloseTo(17.5, 2)       // the cheaper of two competing accepted quotes

    // accept one line in the UI; the rest via "Accept all high-confidence"
    const row = bd.getByRole('listitem').filter({ hasText: /2\.1/ }).first().or(bd.getByRole('row', { name: /2\.1/ }).first())
    await row.getByRole('button', { name: /^Accept/ }).first().click()
    await expect.poll(async () => ((await (await bd.request.get(`/api/v1/bid-settlements/${sid}/ai/proposals`)).json()) as typeof page1).items.find((p) => p.item_no === '2.1')?.status).toBe('accepted')
    await bd.getByRole('button', { name: /Accept all high-confidence/ }).click()
    await bd.getByRole('button', { name: /^Accept all$|^Confirm$|^Accept$/ }).last().click()
    const loadProposals = async () => (await (await bd.request.get(`/api/v1/bid-settlements/${sid}/ai/proposals`)).json()) as typeof page1
    await expect
      .poll(async () => (await loadProposals()).items.filter((p) => p.status === 'accepted').length, { message: 'bulk accept applied', timeout: 30_000 })
      .toBeGreaterThanOrEqual(2)
    const after = await loadProposals()
    const accepted = after.items.filter((p) => p.status === 'accepted')
    expect(accepted.length).toBeGreaterThanOrEqual(2)
    expect(after.items.filter((p) => p.status === 'accepted').every((p) => !p.flags.some((f) => ['stale_rate', 'quote_exclusions', 'vendor_not_eligible'].includes(f)))).toBe(true)
    // flagged and no-source lines were left for a person

    // ---- suggest markup and set it (advisory: nothing changes until "Use these values" is confirmed)
    const before = (await (await bd.request.get(`/api/v1/bid-settlements/${sid}`)).json()) as { default_markup_pct: number }
    await bd.getByRole('button', { name: /Suggest markup/ }).click()
    await expect(bd.getByText(/Suggestions are advice only/)).toBeVisible({ timeout: 120_000 })
    expect(((await (await bd.request.get(`/api/v1/bid-settlements/${sid}`)).json()) as { default_markup_pct: number }).default_markup_pct).toBe(before.default_markup_pct)
    await bd.getByRole('button', { name: /Use these values: Competitive/i }).click()
    await bd.getByRole('button', { name: 'Use these values', exact: true }).last().click()
    await expect
      .poll(async () => ((await (await bd.request.get(`/api/v1/bid-settlements/${sid}`)).json()) as { default_markup_pct: number }).default_markup_pct)
      .not.toBe(before.default_markup_pct)

    // ---- resolve what the AI could not (people set those costs), then submit
    await resolveUnresolvedLines(bd, state.projectId)
    await bd.reload()
    await expect(bd.getByText(/Requires approval by:/)).toBeVisible()
    await bd.getByRole('button', { name: 'Submit for approval' }).click()
    await expect(bd.getByText('Awaiting a different approver (SoD)')).toBeVisible()

    // ---- a different user approves (step-up handled by the helper when MFA is on)
    const mdPage = await login(browser, 'md1', 'Md1Pass!')
    await mdPage.goto(`/projects/${state.projectId}/settlement`)
    const approve = mdPage.getByRole('button', { name: 'Approve' })
    await expect(approve).toBeEnabled()
    await approve.click()
    await expect(mdPage.getByText('approved', { exact: true })).toBeVisible({ timeout: 60_000 })

    // ---- export: the generated workbook downloads
    await mdPage.goto(`/projects/${state.projectId}/export`)
    const [download] = await Promise.all([mdPage.waitForEvent('download'), mdPage.getByRole('button', { name: /Export|Download/ }).first().click()])
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/)

    // ---- the audit trail shows the AI decisions with who and which run
    const auditRes = await mdPage.request.get(`/api/v1/audit/events?entity_type=settlement_ai_proposal&limit=100`)
    expect(auditRes.ok(), await auditRes.text()).toBeTruthy()
    // (the list endpoint never returns payloads; who / what / which project is what it exposes)
    const events = (await auditRes.json()) as { actor_sub: string | null; action: string; project_id: string | null; entity_id: string | null }[]
    const decided = events.filter((e) => e.project_id === state.projectId && e.action === 'update' && e.actor_sub)
    expect(decided.length).toBeGreaterThanOrEqual(2) // the single accept and the bulk accept
    expect(new Set(decided.map((e) => e.entity_id)).size).toBeGreaterThanOrEqual(2) // one event per proposal
    await mdPage.context().close()
    await bd.context().close()
    void csrfHeaders
  })
})
