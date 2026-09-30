import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// DWG support, real backend end to end: real Keycloak login, real upload through the Drawings
// picker, the real `convert` Celery queue, the real sandboxed ODA converter container (no network,
// read-only root), the real DXF pipeline, real S3 downloads. No mocks.
//
// The DWG files come from `make dwg-fixtures` (our own synthetic DXFs converted by the REAL
// converter; backend/tests/fixtures/dwg/, gitignored). Without them this skips loudly.

const FIXTURES = fileURLToPath(new URL('../../../backend/tests/fixtures/dwg', import.meta.url))
const fixture = (name: string) => join(FIXTURES, name)
const CONVERTER = 'installtec_dwg_converter'

interface Drawing {
  id: string
  original_filename: string
  kind: string
  status: string
  content_type: string | null
  sheet_count: number | null
  converted_from_dwg: boolean
  derived_size_bytes: number | null
  derived_sha256: string | null
  converter_version: string | null
  conversion_target: string | null
  conversion_reason: string | null
  error_message: string | null
}
interface Measurement {
  capability: string
  kind: string
  value: number
  unit: string
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await loginViaKeycloak(page, user, pass)
  return page
}

async function listDrawings(page: Page, projectId: string): Promise<Drawing[]> {
  const res = await page.request.get(`/api/v1/projects/${projectId}/drawings`)
  expect(res.ok()).toBeTruthy()
  return (await res.json()) as Drawing[]
}

async function drawingByName(page: Page, projectId: string, name: string): Promise<Drawing> {
  const d = (await listDrawings(page, projectId)).find((x) => x.original_filename === name)
  if (!d) throw new Error(`no drawing ${name}`)
  return d
}

async function waitForStatus(page: Page, projectId: string, name: string, statuses: string[], timeout = 120_000): Promise<Drawing> {
  let d: Drawing | undefined
  await expect
    .poll(async () => (d = await drawingByName(page, projectId, name).catch(() => undefined))?.status, { timeout, intervals: [2_000] })
    .toMatch(new RegExp(`^(${statuses.join('|')})$`))
  return d as Drawing
}

async function measurements(page: Page, drawingId: string): Promise<Measurement[]> {
  const res = await page.request.get(`/api/v1/drawings/${drawingId}/measurements`)
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as Measurement[]).map((m) => ({ ...m, value: Number(m.value) }))
}

const key = (m: Measurement) => `${m.capability}/${m.kind}/${m.unit}`

async function newProject(page: Page, label: string): Promise<string> {
  const code = `DWG-${Date.now().toString(36).toUpperCase()}`
  const created = await page.request.post('/api/v1/projects', { headers: await csrfHeaders(page), data: { code, name: `DWG e2e ${label}` } })
  expect(created.ok(), await created.text()).toBeTruthy()
  return ((await created.json()) as { id: string }).id
}

function requireFixtures() {
  if (existsSync(fixture('manifest.json'))) return
  const reason = 'SKIPPED: DWG fixtures are missing -- run `make dwg-fixtures` (needs deploy/vendor/oda/*.deb).'
  console.error(`\n${'!'.repeat(78)}\n!! ${reason}\n${'!'.repeat(78)}\n`)
  test.skip(true, reason)
}

test('multi-file upload: DWG and DXF side by side, DWG converted, measured like its source DXF, both files downloadable', async ({ browser }) => {
  requireFixtures()
  test.setTimeout(300_000)
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const projectId = await newProject(lead, 'convert')

  await lead.goto(`/projects/${projectId}`)
  // The picker says what it takes, and takes several files including .dwg.
  await expect(lead.getByText('PDF (vector), DXF, DWG (auto-converted)')).toBeVisible()
  const input = lead.getByTestId('drawing-file-input')
  await expect(input).toHaveAttribute('multiple', '')
  expect(await input.getAttribute('accept')).toContain('.dwg')

  // Two DWGs and the DXF the first one was made from -- one upload gesture.
  await input.setInputFiles([fixture('civil_site.dwg'), fixture('civil_site.source.dxf'), fixture('intake_sheet.dwg')])
  await expect(lead.getByRole('status').filter({ hasText: 'Uploaded 3 files' })).toBeVisible({ timeout: 60_000 })

  const dwg = await waitForStatus(lead, projectId, 'civil_site.dwg', ['ready', 'partial', 'failed', 'needs_conversion'])
  const dxf = await waitForStatus(lead, projectId, 'civil_site.source.dxf', ['ready', 'partial', 'failed'])
  const dwg2 = await waitForStatus(lead, projectId, 'intake_sheet.dwg', ['ready', 'partial', 'failed', 'needs_conversion'])
  expect([dwg.status, dwg.error_message]).toEqual(['ready', null])
  expect(dxf.status).toBe('ready')
  expect(dwg2.status).toBe('ready')

  // Original kept as a DWG, derived DXF linked with converter version, target and sha256.
  expect(dwg).toMatchObject({ kind: 'dwg', converted_from_dwg: true, conversion_target: 'ACAD2018', conversion_reason: null })
  expect(dwg.converter_version).toMatch(/^\d+\.\d+/)
  expect(dwg.derived_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(dwg.derived_size_bytes).toBeGreaterThan(1000)
  expect(dxf.kind).toBe('dxf')

  // The pipeline measured the converted file exactly like the DXF it came from.
  const fromDxf = await measurements(lead, dxf.id)
  const fromDwg = await measurements(lead, dwg.id)
  expect(fromDxf.length).toBeGreaterThan(0)
  expect(new Set(fromDxf.map((m) => m.capability))).toEqual(
    new Set(['alignment', 'corridor_area', 'pipe_network_topology', 'trench_prismoidal_volume']),
  )
  const sorted = (ms: Measurement[]) => [...ms].sort((a, b) => key(a).localeCompare(key(b)) || a.value - b.value)
  expect(sorted(fromDwg).map(key)).toEqual(sorted(fromDxf).map(key))
  for (const [i, m] of sorted(fromDwg).entries()) expect(m.value).toBeCloseTo(sorted(fromDxf)[i].value, 4)

  // UI: the project list marks it DWG; the sheet page says "Converted from DWG" and offers both files.
  await lead.reload()
  await expect(lead.getByRole('link', { name: 'civil_site.dwg' })).toBeVisible()
  await lead.getByRole('link', { name: 'civil_site.dwg' }).click()
  await expect(lead.getByTestId('dwg-provenance')).toContainText('Converted from DWG')
  await expect(lead.getByTestId('dwg-provenance')).toContainText('ACAD2018')
  const original = lead.getByRole('link', { name: 'Download original DWG' })
  const derived = lead.getByRole('link', { name: 'Download converted DXF' })
  await expect(original).toBeVisible()
  await expect(derived).toBeVisible()

  const originalBytes = await (await lead.request.get((await original.getAttribute('href')) as string)).body()
  expect(originalBytes.subarray(0, 4).toString('latin1')).toBe('AC10')
  expect(originalBytes.equals(readFileSync(fixture('civil_site.dwg')))).toBeTruthy() // byte-identical to what was uploaded
  const derivedRes = await lead.request.get((await derived.getAttribute('href')) as string)
  expect(derivedRes.ok()).toBeTruthy()
  const derivedBytes = await derivedRes.body()
  expect(derivedBytes.subarray(0, 8000).toString('latin1')).toContain('SECTION')
  expect(derivedBytes.length).toBe(dwg.derived_size_bytes)

  // A plain DXF has no DWG provenance block.
  await lead.goto(`/projects/${projectId}/drawings/${dxf.id}`)
  await expect(lead.getByTestId('dwg-provenance')).toHaveCount(0)
})

test('a corrupt DWG and a .dwg that is really a PDF: needs conversion with a reason, or detected as a PDF -- never a 500', async ({ browser }) => {
  requireFixtures()
  test.setTimeout(240_000)
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const projectId = await newProject(lead, 'bad files')
  const serverErrors: string[] = []
  lead.on('response', (r) => {
    if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`)
  })

  await lead.goto(`/projects/${projectId}`)
  await lead.getByTestId('drawing-file-input').setInputFiles([fixture('corrupt.dwg'), fixture('pdf_named.dwg')])
  await expect(lead.getByRole('status').filter({ hasText: 'Uploaded 2 files' })).toBeVisible({ timeout: 60_000 })

  // The real converter rejects the corrupt file: parked, with the reason and the manual workaround.
  const corrupt = await waitForStatus(lead, projectId, 'corrupt.dwg', ['needs_conversion', 'ready', 'failed'])
  expect(corrupt.status).toBe('needs_conversion')
  expect(corrupt).toMatchObject({ kind: 'dwg', conversion_reason: 'convert_failed', converted_from_dwg: false })
  expect(corrupt.error_message).toContain('could not be converted')
  expect(corrupt.error_message).toContain('save/export it as DXF (or PDF)')

  await lead.goto(`/projects/${projectId}/drawings/${corrupt.id}`)
  await expect(lead.getByText('needs conversion', { exact: true }).first()).toBeVisible()
  await expect(lead.getByRole('alert').filter({ hasText: 'could not be converted' })).toBeVisible()
  await expect(lead.getByRole('button', { name: 'Retry conversion' })).toBeVisible()
  await expect(lead.getByRole('link', { name: 'Download original DWG' })).toBeVisible()
  await expect(lead.getByRole('link', { name: 'Download converted DXF' })).toHaveCount(0)

  // The PDF wearing a .dwg name is a PDF: no conversion, no DWG badge.
  const pdf = await drawingByName(lead, projectId, 'pdf_named.dwg')
  expect(pdf).toMatchObject({ kind: 'vector_pdf', content_type: 'application/pdf', converted_from_dwg: false })
  expect(pdf.conversion_reason).toBeNull()

  // A .dwg with no DWG content at all is refused at upload with a readable message.
  await lead.goto(`/projects/${projectId}`)
  await lead.getByTestId('drawing-file-input').setInputFiles({ name: 'notes.dwg', mimeType: 'application/octet-stream', buffer: Buffer.from('just some text') })
  await expect(lead.getByRole('alert').filter({ hasText: 'notes.dwg' })).toContainText('not a valid DWG')

  expect(serverErrors).toEqual([])
})

test('converter down -> needs conversion (unavailable), converter back -> Retry conversion reaches ready', async ({ browser }) => {
  requireFixtures()
  test.setTimeout(360_000)
  const lead = await login(browser, 'lead1', 'Lead1Pass!')
  const projectId = await newProject(lead, 'converter down')

  execFileSync('docker', ['stop', CONVERTER], { stdio: 'pipe' })
  try {
    // The heartbeat goes stale after DWG_HEARTBEAT_MAX_AGE_S (30s).
    await lead.waitForTimeout(36_000)
    await lead.goto(`/projects/${projectId}`)
    await lead.getByTestId('drawing-file-input').setInputFiles(fixture('intake_sheet.dwg'))
    const parked = await waitForStatus(lead, projectId, 'intake_sheet.dwg', ['needs_conversion', 'ready', 'failed'], 90_000)
    expect(parked).toMatchObject({ status: 'needs_conversion', conversion_reason: 'unavailable' })
    expect(parked.error_message).toContain('not installed or not running')
    expect(parked.error_message).toContain('save/export it as DXF (or PDF)')
  } finally {
    execFileSync('docker', ['start', CONVERTER], { stdio: 'pipe' })
  }

  // Back up: wait for a fresh heartbeat, then retry from the UI.
  await expect
    .poll(
      () => execFileSync('docker', ['exec', 'installtec_celery_worker_convert', 'cat', '/spool/heartbeat.json']).toString(),
      { timeout: 60_000, intervals: [2_000] },
    )
    .toContain('"ok": true')
  const drawing = await drawingByName(lead, projectId, 'intake_sheet.dwg')
  await lead.goto(`/projects/${projectId}/drawings/${drawing.id}`)
  await lead.getByRole('button', { name: 'Retry conversion' }).click()
  // Not needs_conversion: that is the state we are retrying out of, so it must not count as the answer.
  const done = await waitForStatus(lead, projectId, 'intake_sheet.dwg', ['ready', 'failed', 'partial'], 120_000)
  expect([done.status, done.error_message]).toEqual(['ready', null])
  expect(done).toMatchObject({ converted_from_dwg: true, conversion_reason: null })
  await lead.reload()
  await expect(lead.getByTestId('dwg-provenance')).toContainText('Converted from DWG')
})
