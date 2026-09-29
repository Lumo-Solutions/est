import { expect, test } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak } from './helpers'

// The takeoff screen renders PDF sheets with pdf.js, whose worker is an ES
// module (assets/pdf.worker.min-*.mjs). nginx used to serve .mjs as
// application/octet-stream, so browsers refused to run it ("Setting up fake
// worker failed") and the viewer showed "Failed to render PDF" -- a bug the
// old viewer spec never saw because its fixture drawing is a DXF. This spec
// uploads a small hand-built VECTOR PDF, waits for extraction, and asserts the
// canvas actually painted.

function buildVectorPdf(): Buffer {
  // A rectangle, a diagonal, and a line of text -- all vector operators.
  const content =
    'q 2 w 0 0 0 RG 50 50 495 320 re S 1 0 0 RG 50 50 m 545 370 l S ' +
    'BT /F1 28 Tf 120 200 Td (VECTOR PLAN A-101) Tj ET Q'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 420] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let out = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(out.length)
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xrefAt = out.length
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  out += offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

test('the takeoff screen renders a vector PDF sheet (pdf.js worker loads as JavaScript)', async ({ page }) => {
  test.setTimeout(240_000)
  await loginViaKeycloak(page, 'lead1', 'Lead1Pass!')

  // lead_estimator may create projects and becomes the owner/member.
  const created = await page.request.post('/api/v1/projects', {
    headers: await csrfHeaders(page),
    data: { code: `QA-PDF-${Date.now()}`, name: 'Vector PDF viewer check' },
  })
  expect(created.status()).toBe(201)
  const projectId = (await created.json()).id as string

  const uploaded = await page.request.post(`/api/v1/projects/${projectId}/drawings`, {
    headers: await csrfHeaders(page),
    multipart: { file: { name: 'vector-plan.pdf', mimeType: 'application/pdf', buffer: buildVectorPdf() } },
  })
  expect(uploaded.status()).toBe(201)
  const drawingId = (await uploaded.json()).id as string

  // Upload only stores the file; extraction is a separate call (the UI's
  // useUploadDrawing does the same two steps back to back).
  const ingest = await page.request.post(`/api/v1/drawings/${drawingId}/ingest`, {
    headers: await csrfHeaders(page),
  })
  expect(ingest.status()).toBe(202)

  // Extraction is asynchronous (celery); wait for a usable sheet.
  await expect
    .poll(
      async () => {
        const r = await page.request.get(`/api/v1/drawings/${drawingId}/sheets`)
        return r.ok() ? ((await r.json()) as unknown[]).length : 0
      },
      { timeout: 150_000, intervals: [2_000] },
    )
    .toBeGreaterThan(0)

  const consoleErrors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text())
  })
  const workerResponses: { url: string; type: string }[] = []
  page.on('response', (r) => {
    if (/pdf\.worker.*\.mjs/.test(r.url())) workerResponses.push({ url: r.url(), type: r.headers()['content-type'] ?? '' })
  })

  await page.goto(`/projects/${projectId}/drawings/${drawingId}/sheets/0`)
  const canvas = page.locator('canvas').first()
  await expect(canvas).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/Failed to render PDF/)).toHaveCount(0)

  // The canvas must actually contain drawn (non-white) pixels.
  await expect
    .poll(
      () =>
        canvas.evaluate((el) => {
          const c = el as HTMLCanvasElement
          if (!c.width || !c.height) return 0
          const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data
          let dark = 0
          for (let i = 0; i < data.length; i += 4) if (data[i] + data[i + 1] + data[i + 2] < 600) dark++
          return dark
        }),
      { timeout: 30_000 },
    )
    .toBeGreaterThan(200)

  // The worker was fetched and served as JavaScript, not octet-stream.
  expect(workerResponses.length).toBeGreaterThan(0)
  for (const w of workerResponses) expect(w.type).toMatch(/javascript/)
  expect(consoleErrors).toEqual([])
})
