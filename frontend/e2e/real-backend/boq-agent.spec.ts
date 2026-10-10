import { execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { csrfHeaders, loginViaKeycloak, submitSettlementForApproval } from './helpers'

// The BOQ agent end to end on the real dev stack, the MOCK provider (no key, no cost):
//   create project + BOQ -> upload the tender folder (fast, AI-free index) -> Run estimation agent (Agent tab)
//   -> trace + coverage -> settlement banner -> submit is refused while an agent line is unconfirmed
//   -> confirm (drawer, then API) -> submit as bd1 -> approval request exists.
// Preconditions: `make up`, `make migrate`, `make seed`, `make dev-seed-ai-demo`, the celery-worker-agent container running,
// and AI_PROVIDER=mock for the backend and the agent worker (start them with `AI_PROVIDER=mock docker compose up -d backend
// celery-worker-agent`; deploy/.env itself is not changed). Everything created is tagged AI-DEMO-E2E-* and removed by
// `make dev-clean-demo-data`.

const PACK_ROOT = 'Al Reem Package 3'
// [item_no, description, uom, quantity, parent item_no] -- the designed demo BOQ (backend/app/demo/ai_demo.py)
const HEADINGS: [string, string][] = [['1', 'EARTHWORKS'], ['2', 'DRAINAGE'], ['3', 'ROADWORKS']]
const LINES: [string, string, string, number, string][] = [
  ['1.1', 'Excavate in all types of soil for roadway and dispose off site', 'm3', 12500, '1'],
  ['1.2', 'Trim and compact formation level to receive sub-base', 'm2', 7300, '1'],
  ['2.1', 'Supply, lay and joint 300mm diameter uPVC SN8 sewer pipe including bedding and testing', 'm', 245, '2'],
  ['2.3', 'Precast concrete manhole 1200mm internal diameter complete with cover and frame', 'nr', 12, '2'],
  ['3.2', 'Precast concrete kerb Type A 300x150 supply and lay', 'm', 1040, '3'],
  ['3.3', 'Thermoplastic road marking 100mm centre line', 'm', 520, '3'],
]

function writeAiPack(): string {
  const remote = `/tmp/ai-pack-${Date.now()}`
  execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'write-ai-demo-pack', '--out', remote], { stdio: 'pipe' })
  const dir = mkdtempSync(join(tmpdir(), 'agent-pack-'))
  execFileSync('docker', ['cp', `installtec_backend:${remote}/.`, dir], { stdio: 'pipe' })
  return dir
}

async function login(browser: Browser, user: string, pass: string): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.error(`PAGEERROR (${user}): ${e.message}`))
  await loginViaKeycloak(page, user, pass)
  return page
}

test.describe.serial('BOQ agent (mock provider)', () => {
  test.setTimeout(600_000)
  const state = { projectId: '', code: '', runId: '', settlementId: '' }

  test('fast AI-free upload -> agent run -> trace -> settlement gate -> confirm -> submit', async ({ browser }) => {
    const lead = await login(browser, 'lead1', 'Lead1Pass!')
    const status = (await (await lead.request.get('/api/v1/ai/status')).json()) as { provider: string }
    expect(status.provider, 'start the backend and the agent worker with AI_PROVIDER=mock').toBe('mock')
    expect(((await (await lead.request.get('/api/v1/tender-intake/settings')).json()) as { ai_classify: boolean }).ai_classify).toBe(false)

    // ---- project + BOQ (headings, then lines under them)
    const headers = await csrfHeaders(lead)
    state.code = `AI-DEMO-E2E-AG${Date.now().toString(36).toUpperCase()}`
    const created = await lead.request.post('/api/v1/projects', { headers, data: { code: state.code, name: 'BOQ agent walkthrough' } })
    expect(created.ok(), await created.text()).toBeTruthy()
    state.projectId = ((await created.json()) as { id: string }).id
    const parent: Record<string, string> = {}
    for (const [no, desc] of HEADINGS) {
      const r = await lead.request.post(`/api/v1/projects/${state.projectId}/boq-items`, { headers, data: { item_no: no, description: desc } })
      expect(r.ok(), await r.text()).toBeTruthy()
      parent[no] = ((await r.json()) as { id: string }).id
    }
    for (const [no, desc, uom, qty, p] of LINES) {
      const r = await lead.request.post(`/api/v1/projects/${state.projectId}/boq-items`, {
        headers, data: { item_no: no, description: desc, uom, boq_quantity: qty, parent_id: parent[p] },
      })
      expect(r.ok(), await r.text()).toBeTruthy()
    }
    execFileSync('docker', ['exec', '-w', '/app', 'installtec_backend', 'python', '-m', 'app.cli', 'seed-ai-demo-quotes', '--project', state.code], { stdio: 'pipe' })

    // ---- the tender folder: indexed by the rules, no model call
    const pack = writeAiPack()
    await lead.goto(`/projects/${state.projectId}`)
    await lead.getByTestId('tender-folder-input').setInputFiles(join(pack, PACK_ROOT))
    await lead.getByRole('button', { name: 'Upload 9 files' }).click()
    await expect
      .poll(async () => {
        const items = ((await (await lead.request.get(`/api/v1/projects/${state.projectId}/tender-documents?limit=100`)).json()) as { items: { status: string; classified_by: string | null }[] }).items
        return items.length === 9 && items.every((d) => !['received', 'processing', 'pending_upload'].includes(d.status)) && items.every((d) => d.classified_by !== 'ai')
      }, { timeout: 120_000, intervals: [2_000] })
      .toBe(true)

    // ---- Agent tab: run it
    await lead.goto(`/projects/${state.projectId}`)
    await lead.getByRole('tab', { name: 'Agent' }).click()
    await lead.getByRole('button', { name: 'Run estimation agent' }).click()
    await expect(lead.getByRole('region', { name: /Run summary|summary/i }).or(lead.getByText('Done').first())).toBeVisible({ timeout: 240_000 })
    const runs = (await (await lead.request.get(`/api/v1/projects/${state.projectId}/agent/runs`)).json()) as { id: string; status: string }[]
    state.runId = runs[0].id
    await expect
      .poll(async () => ((await (await lead.request.get(`/api/v1/agent/runs/${state.runId}`)).json()) as { status: string }).status, { timeout: 240_000, intervals: [3_000] })
      .toBe('done')
    const run = (await (await lead.request.get(`/api/v1/agent/runs/${state.runId}`)).json()) as {
      steps_total: number; settlement_id: string; cost_usd: number; sections: { status: string; coverage: { lines_total: number } | null }[]; summary: { applied: { applied: number } }
    }
    state.settlementId = run.settlement_id
    expect(run.steps_total).toBeGreaterThan(5)
    expect(run.cost_usd).toBe(0)
    expect(run.sections.every((s) => s.status === 'done' && s.coverage)).toBeTruthy()
    expect(run.summary.applied.applied).toBeGreaterThan(0)
    const steps = (await (await lead.request.get(`/api/v1/agent/runs/${state.runId}/steps`)).json()) as { tool: string }[]
    expect(steps.map((s) => s.tool)).toEqual(expect.arrayContaining(['search_files', 'cost_candidates', 'propose_line', 'finish_section']))
    await expect(lead.getByText(/propose/i).first()).toBeVisible() // the trace is on screen

    // ---- the gate: the agent's lines are unconfirmed, so submit is refused by the server
    const summary = (await (await lead.request.get(`/api/v1/bid-settlements/${state.settlementId}/agent-summary`)).json()) as { agent_lines: number; unconfirmed: number }
    expect(summary.unconfirmed).toBeGreaterThan(0)
    const bd = await login(browser, 'bd1', 'Bd1Pass!')
    const early = await bd.request.post(`/api/v1/bid-settlements/${state.settlementId}/submit`, { headers: await csrfHeaders(bd) })
    expect(early.status()).toBe(409)
    expect(await early.text()).toContain('estimation agent')

    // ---- settlement page: the banner, then confirm one line in the drawer, the rest by the API
    await lead.goto(`/projects/${state.projectId}/settlement`)
    await expect(lead.getByRole('status').filter({ hasText: /agent lines? need/i })).toBeVisible({ timeout: 60_000 })
    await lead.getByRole('button', { name: /Agent: source/ }).first().click()
    await lead.getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect.poll(async () => ((await (await lead.request.get(`/api/v1/bid-settlements/${state.settlementId}/agent-summary`)).json()) as { unconfirmed: number }).unconfirmed, { timeout: 30_000 }).toBe(summary.unconfirmed - 1)
    const lines = (await (await lead.request.get(`/api/v1/bid-settlements/${state.settlementId}/agent-lines`)).json()) as {
      line_id: string; agent_proposal_id: string; agent_confirmed_by: string | null
    }[]
    for (const l of lines.filter((x) => !x.agent_confirmed_by)) {
      const r = await lead.request.post(`/api/v1/bid-settlements/${state.settlementId}/lines/${l.line_id}/agent-confirm`, {
        headers: await csrfHeaders(lead), data: { proposal_id: l.agent_proposal_id },
      })
      expect(r.ok(), await r.text()).toBeTruthy()
    }
    expect(((await (await lead.request.get(`/api/v1/bid-settlements/${state.settlementId}/agent-summary`)).json()) as { unconfirmed: number }).unconfirmed).toBe(0)

    // ---- submit as bd1 (the agent is never the submitter); the person who submits is recorded
    await submitSettlementForApproval(bd, state.projectId)
    const settlement = (await (await bd.request.get(`/api/v1/bid-settlements/${state.settlementId}`)).json()) as { status: string; approval_request_id: string | null; submitted_by: string | null }
    expect(settlement.status).toBe('submitted')
    expect(settlement.approval_request_id).toBeTruthy()
    expect(settlement.submitted_by).toBeTruthy()
  })
})
