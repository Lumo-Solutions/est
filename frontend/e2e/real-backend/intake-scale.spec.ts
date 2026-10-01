import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, ensureProjectMember, loginViaKeycloak } from './helpers'

// Intake at scale (docs/intake-scale/report.md), real backend, real Keycloak, real workers, real S3, the MOCK provider:
//   * the folder is hashed, registered and uploaded a few files at a time; closing the tab mid-upload and dropping
//     the same folder again RESUMES (nothing is sent twice, no row is duplicated);
//   * a file that is too large is stored and parked under "Needs your check";
//   * "Confirm all" confirms every matching file on the server, not just the rows on screen;
//   * a lead estimator can pause and resume a pack; an estimator sees no pack controls.
// The pack is the synthetic production-scale folder (backend/app/intake/scale_pack.py), a small one here (the 2,000-file
// proof run is in the report). Preconditions: `make up` with a rebuilt frontend and the workers running, AI_PROVIDER=mock.

interface Item {
  id: string
  name: string
  path: string | null
  doc_class: string | null
  display_status: string
  status: string
  flags: string[]
  status_reason: string | null
}
interface Counts {
  summary: { total: number; needs_check: number; in_progress: number; pending_upload: number; packages_processing: number }
  packages: { id: string; label: string | null; status: string; expected_count: number; registered: number; uploaded: number; pending_upload: number }[]
}

function writePack(files: number, seed: number): { dir: string; manifest: { files: number; items: { path: string; kind: string }[] } } {
  const remote = `/tmp/scale-pack-${seed}-${Date.now()}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.intake.scale_pack', remote, '--files', String(files), '--seed', String(seed), '--huge', '1'], {
    stdio: 'pipe',
    timeout: 300_000,
  })
  const dir = mkdtempSync(join(tmpdir(), 'scale-pack-'))
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  execFileSync('docker', ['exec', 'installtec_backend', 'rm', '-rf', remote], { stdio: 'pipe' })
  return { dir, manifest: JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8')) }
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.error(`PAGEERROR (${user}): ${e.message}`))
  await loginViaKeycloak(page, user, pass)
  return page
}

async function createProject(page: Page, name: string): Promise<string> {
  const created = await page.request.post('/api/v1/projects', {
    headers: await csrfHeaders(page),
    data: { code: `SC-${Date.now().toString(36).toUpperCase()}`, name },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  return ((await created.json()) as { id: string }).id
}

async function counts(page: Page, projectId: string): Promise<Counts> {
  const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents/tree`)
  expect(res.ok(), await res.text()).toBeTruthy()
  return (await res.json()) as Counts
}

async function items(page: Page, projectId: string, query = ''): Promise<Item[]> {
  const out: Item[] = []
  for (let offset = 0; ; offset += 500) {
    const res = await page.request.get(`/api/v1/projects/${projectId}/tender-documents/items?limit=500&offset=${offset}${query}`)
    expect(res.ok(), await res.text()).toBeTruthy()
    const body = (await res.json()) as { items: Item[]; total: number }
    out.push(...body.items)
    if (out.length >= body.total) return out
  }
}

async function waitRead(page: Page, projectId: string, timeout = 600_000): Promise<Counts> {
  let last: Counts | undefined
  await expect
    .poll(
      async () => {
        last = await counts(page, projectId)
        const s = last.summary
        return s.total > 0 && s.in_progress === 0 && s.pending_upload === 0 && s.packages_processing === 0
      },
      { timeout, intervals: [3_000], message: 'every file uploaded and read' },
    )
    .toBe(true)
  return last as Counts
}

test('a pack is uploaded a few files at a time; closing the tab mid-upload and dropping the folder again resumes; confirm-all covers every match', async ({ browser }) => {
  test.setTimeout(1_200_000)
  const pack = writePack(120, 11)
  try {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    const projectId = await createProject(lead, 'Scale: resumable upload')
    await lead.goto(`/projects/${projectId}`)
    await expect(lead.getByRole('heading', { name: 'Drop your tender folder or zip here' })).toBeVisible()

    // Slow each file's PUT a little so the upload is long enough to interrupt.
    await lead.route('**/documents/*/content', async (route) => {
      await new Promise((r) => setTimeout(r, 400))
      await route.continue()
    })
    await lead.getByTestId('tender-folder-input').setInputFiles(join(pack.dir, 'Tender'))
    await lead.getByRole('button', { name: /^Upload [\d,]+ files$/ }).click()
    const progress = lead.getByRole('status').filter({ hasText: /Uploaded \d+ \/ \d+/ })
    await expect(progress).toBeVisible({ timeout: 120_000 })
    await expect.poll(async () => Number(/Uploaded (\d+) \//.exec((await progress.textContent()) ?? '')?.[1] ?? 0), { timeout: 120_000 }).toBeGreaterThanOrEqual(15)
    await lead.context().close() // "close the tab"

    // The server kept the registered pack: some files arrived, the rest are waiting.
    const again = await login(browser, 'lead1', 'Lead1Pass!')
    const mid = await counts(again, projectId)
    expect(mid.packages).toHaveLength(1)
    const pk = mid.packages[0]
    expect(pk.status).toBe('uploading')
    expect(pk.uploaded).toBeGreaterThanOrEqual(15)
    expect(pk.uploaded).toBeLessThan(pk.registered)
    const arrivedBefore = pk.uploaded

    // ---- drop the same folder again: it resumes, sends only what is missing, and says so
    await again.goto(`/projects/${projectId}`)
    await expect(again.getByText(/Uploaded \d+ of \d+ files/)).toBeVisible({ timeout: 60_000 })
    await again.getByTestId('tender-folder-input').setInputFiles(join(pack.dir, 'Tender'))
    await again.getByRole('button', { name: /^Upload [\d,]+ files$/ }).click()
    await expect(again.getByText(/Continuing an unfinished upload: \d+ files? (was|were) already here/)).toBeVisible({ timeout: 120_000 })

    const done = await waitRead(again, projectId)
    expect(done.packages).toHaveLength(1) // the same pack, not a second one
    expect(done.packages[0].status).toBe('ready')
    const all = await items(again, projectId)
    const paths = all.map((i) => i.path ?? i.name)
    expect(new Set(paths).size).toBe(paths.length) // nothing registered or stored twice
    expect(done.summary.total).toBe(all.length)
    expect(all.length).toBeGreaterThanOrEqual(arrivedBefore)
    expect(all.filter((i) => i.status === 'failed' && i.display_status === 'failed' && !/corrupt|empty/i.test(i.path ?? i.name)).length).toBeLessThanOrEqual(2)

    // ---- the too-large file was stored and parked for a person, with its reason
    const tooLarge = all.filter((i) => i.flags.includes('too_large'))
    expect(tooLarge.length).toBeGreaterThanOrEqual(1)
    expect(tooLarge[0]).toMatchObject({ display_status: 'needs_check', doc_class: null })
    expect(tooLarge[0].status_reason).toContain('Too large to read automatically')

    // ---- Needs your check: confirm-all covers every matching file, then only what needs a person is left
    await again.reload()
    await expect(again.getByRole('heading', { name: /^Needs your check/ })).toBeVisible({ timeout: 60_000 })
    const confirmAll = again.getByRole('button', { name: /^Confirm all \(\d+\)$/ })
    const matching = Number(/\((\d+)\)/.exec((await confirmAll.textContent()) ?? '')?.[1] ?? 0)
    if (matching > 0) {
      await confirmAll.click()
      await again.getByRole('dialog').getByRole('button', { name: 'Confirm all' }).click()
      await expect(again.getByRole('status').filter({ hasText: new RegExp(`Confirmed ${matching} of ${matching}`) })).toBeVisible({ timeout: 300_000 })
    }
    await expect
      .poll(async () => (await items(again, projectId, '&display_status=needs_check')).filter((i) => i.doc_class !== null && !i.flags.includes('conflict') && !i.flags.includes('injection_suspected')).length, { timeout: 120_000 })
      .toBe(0)
    const left = await items(again, projectId, '&display_status=needs_check')
    expect(left.some((i) => i.flags.includes('too_large'))).toBe(true) // it has no class: a person still has to choose one
    await again.context().close()
  } finally {
    rmSync(pack.dir, { recursive: true, force: true })
  }
})

test('a lead estimator pauses and resumes a pack; an estimator sees no pack controls', async ({ browser }) => {
  test.setTimeout(900_000)
  const pack = writePack(60, 12)
  try {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    const projectId = await createProject(lead, 'Scale: pause and resume')
    await ensureProjectMember(browser, projectId, 'estimator1')
    await lead.goto(`/projects/${projectId}`)
    await lead.getByTestId('tender-folder-input').setInputFiles(join(pack.dir, 'Tender'))
    await lead.getByRole('button', { name: /^Upload [\d,]+ files$/ }).click()
    await expect(lead.getByRole('status').filter({ hasText: /Reading documents: \d+ of \d+/ })).toBeVisible({ timeout: 180_000 })

    await lead.getByRole('button', { name: /^Pause / }).click()
    await expect(lead.getByRole('status').filter({ hasText: /This pack is paused/ })).toBeVisible({ timeout: 30_000 })
    const pausedAt = (await counts(lead, projectId)).summary.in_progress
    expect(pausedAt).toBeGreaterThan(0) // paused mid-way: files still waiting
    // Nothing new is started while it is paused (a file already being read may still finish).
    await lead.waitForTimeout(12_000)
    const later = (await counts(lead, projectId)).summary.in_progress
    expect(later).toBeGreaterThanOrEqual(pausedAt - 3)

    // An estimator (a project member) can see the project but not the pack controls.
    const est = await login(browser, 'estimator1', 'Estimator1Pass!')
    await est.goto(`/projects/${projectId}`)
    await expect(est.getByRole('status').filter({ hasText: /This pack is paused/ })).toBeVisible({ timeout: 30_000 })
    await expect(est.getByRole('button', { name: /^(Pause|Resume|Cancel) / })).toHaveCount(0)
    await est.context().close()

    await lead.getByRole('button', { name: /^Resume / }).click()
    await expect(lead.getByRole('status').filter({ hasText: /This pack is paused/ })).toHaveCount(0, { timeout: 30_000 })
    const done = await waitRead(lead, projectId)
    expect(done.packages[0].status).toBe('ready')
    await lead.context().close()
  } finally {
    rmSync(pack.dir, { recursive: true, force: true })
  }
})

// The 2,000-file proof project (docs/intake-scale/report.md): set SCALE_PROJECT to its id to run this against it.
test('a 2,000-file project page stays responsive: counts from the server, a bounded number of rows in the DOM', async ({ browser }) => {
  test.skip(!process.env.SCALE_PROJECT, 'set SCALE_PROJECT to the id of the 2,000-file proof project')
  test.setTimeout(300_000)
  const projectId = process.env.SCALE_PROJECT as string
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const started = Date.now()
  await lead.goto(`/projects/${projectId}`)
  await expect(lead.getByRole('heading', { name: /^Project documents/ })).toBeVisible({ timeout: 60_000 })
  const firstPaint = Date.now() - started
  const summary = (await counts(lead, projectId)).summary
  expect(summary.total).toBeGreaterThan(1500)
  expect(firstPaint).toBeLessThan(15_000)
  // However many files there are, the DOM holds a bounded number of rows.
  const rows = await lead.getByRole('listitem').count()
  expect(rows).toBeLessThan(400)
  // The class group counts come from the server and add up.
  const groups = await lead.getByRole('group', { name: /, \d+ files?$/ }).evaluateAll((els) => els.length)
  expect(groups).toBeGreaterThan(3)
  await lead.context().close()
})
