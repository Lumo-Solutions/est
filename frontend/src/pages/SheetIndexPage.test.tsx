import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let allowed = true
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: () => allowed }),
}))

import { sheetsInProgress } from '../features/drawings/api'
import type { DrawingSheetOut } from '../types/api'
import { SheetIndexPage } from './SheetIndexPage'

function sheet(i: number, over: Partial<DrawingSheetOut> = {}): DrawingSheetOut {
  return {
    id: `s${i}`,
    drawing_id: 'd1',
    sheet_index: i,
    source_name: `Sheet ${i}`,
    is_raster: false,
    text_char_count: 10,
    title_block: null,
    drawing_number: `A-${i}`,
    sheet_title: `Plan ${i}`,
    revision: null,
    issue_date: null,
    discipline: null,
    scale_text: null,
    scale_ratio: null,
    scale_source: null,
    scale_confidence: null,
    scale_disagreement: false,
    extraction_status: 'ready',
    annotations_status: null,
    ...over,
  }
}

const ANNOTATIONS = {
  items: [
    { id: 'a1', sheet_id: 's0', page: 1, text: 'Slab 200mm', kind: 'thickness', value: 200, unit: 'mm', material: 'concrete', bbox: null, source: 'ai', confidence: 0.9 },
    { id: 'a2', sheet_id: 's0', page: 1, text: 'Wall type W1', kind: 'note', value: null, unit: null, material: null, bbox: null, source: 'ai', confidence: 0.8 },
  ],
  total: 2,
  limit: 1000,
  offset: 0,
}

interface Calls {
  sheets: number
  posts: { url: string; body: unknown }[]
}

function mockFetch(sheets: DrawingSheetOut[], aiAvailable = true): Calls {
  const calls: Calls = { sheets: 0, posts: [] }
  const json = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        calls.posts.push({ url, body: JSON.parse(String(init.body)) })
        return json({ queued_sheets: 3 }, 202)
      }
      if (url.endsWith('/drawings/d1/sheets')) {
        calls.sheets += 1
        return json(sheets)
      }
      if (url.endsWith('/drawings/d1')) {
        return json({ id: 'd1', original_filename: 'plans.pdf', status: 'ready', kind: 'pdf' })
      }
      if (url.includes('/drawing-annotations?')) return json(ANNOTATIONS)
      if (url.endsWith('/ai/status')) {
        return json({
          provider: 'x',
          external: true,
          configured: true,
          external_ai_allowed: aiAvailable,
          available: aiAvailable,
          message: aiAvailable ? null : 'AI is switched off.',
        })
      }
      return json({}, 404)
    }),
  )
  return calls
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/drawings/d1']}>
        <Routes>
          <Route path="/projects/:projectId/drawings/:drawingId" element={<SheetIndexPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  allowed = true
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('SheetIndexPage annotations', () => {
  it('shows a labelled badge for every annotation status, and links each row to the viewer', async () => {
    const statuses: (string | null)[] = [null, 'queued', 'done', 'unavailable', 'failed', 'skipped']
    mockFetch(statuses.map((st, i) => sheet(i, { annotations_status: st })))
    renderPage()
    for (const label of [
      'Annotations: not read',
      'Annotations: queued',
      'Annotations: read',
      'Annotations: AI unavailable',
      'Annotations: failed',
      'Annotations: nothing to read',
    ]) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.getAllByText('Extraction: ready')).toHaveLength(6)
    const link = screen.getByRole('link', { name: 'Open sheet 3 in takeoff viewer' })
    expect(link).toHaveAttribute('href', '/projects/p1/drawings/d1/sheets/2')
    expect(screen.getAllByRole('link', { name: /in takeoff viewer/ })).toHaveLength(6)
  })

  it('summarises progress', async () => {
    mockFetch([
      sheet(0, { annotations_status: 'done' }),
      sheet(1, { extraction_status: 'failed' }),
      sheet(2, { annotations_status: 'done' }),
    ])
    renderPage()
    expect(await screen.findByText('2 of 3 sheets extracted')).toBeInTheDocument()
    expect(screen.getByText('2 of 3 sheets have annotations read')).toBeInTheDocument()
  })

  it('polls every 2s while a sheet is in progress', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockFetch([sheet(0, { extraction_status: 'extracting' })])
    renderPage()
    await screen.findByText('0 of 1 sheets extracted')
    const first = calls.sheets
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4500)
    })
    expect(calls.sheets).toBeGreaterThanOrEqual(first + 2)
  })

  it('stops polling when nothing is in progress', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockFetch([sheet(0, { annotations_status: 'done' })])
    renderPage()
    await screen.findByText('1 of 1 sheets extracted')
    const first = calls.sheets
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(calls.sheets).toBe(first)
  })

  it('sheetsInProgress detects extraction and queued annotations', () => {
    expect(sheetsInProgress(undefined)).toBe(false)
    expect(sheetsInProgress([sheet(0)])).toBe(false)
    expect(sheetsInProgress([sheet(0, { extraction_status: 'embedding' })])).toBe(true)
    expect(sheetsInProgress([sheet(0, { annotations_status: 'queued' })])).toBe(true)
    expect(sheetsInProgress([sheet(0, { annotations_status: 'failed', extraction_status: 'failed' })])).toBe(false)
  })

  it('hides the read buttons from roles without access', async () => {
    allowed = false
    mockFetch([sheet(0)])
    renderPage()
    await screen.findByText('1 of 1 sheets extracted')
    expect(screen.queryByRole('button', { name: 'Read annotations with AI' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Re-read all' })).toBeNull()
  })

  it('posts force=false, then shows the queued count', async () => {
    const calls = mockFetch([sheet(0)])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Read annotations with AI' }))
    expect(await screen.findByText('3 sheets queued for annotation reading')).toBeInTheDocument()
    expect(calls.posts).toEqual([
      { url: '/api/v1/projects/p1/drawing-annotations:read', body: { drawing_id: 'd1', force: false } },
    ])
  })

  it('re-read all asks for confirmation and posts force=true', async () => {
    const calls = mockFetch([sheet(0)])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Re-read all' }))
    expect(calls.posts).toHaveLength(0)
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Re-read all' }))
    await waitFor(() => expect(calls.posts).toHaveLength(1))
    expect(calls.posts[0].body).toEqual({ drawing_id: 'd1', force: true })
  })

  it('says plainly that annotations cannot be read when AI is unavailable', async () => {
    mockFetch([sheet(0)], false)
    renderPage()
    expect(await screen.findByText(/Annotations cannot be read now/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Read annotations with AI' })).toBeDisabled()
  })

  it('expands the AI-read annotations for a sheet', async () => {
    mockFetch([sheet(0, { annotations_status: 'done' }), sheet(1)])
    renderPage()
    const toggle = await screen.findByRole('button', { name: '2 annotations' })
    expect(screen.queryByText('Slab 200mm')).toBeNull()
    fireEvent.click(toggle)
    expect(screen.getByText('Slab 200mm')).toBeInTheDocument()
    expect(screen.getByText('200 mm')).toBeInTheDocument()
    expect(screen.getByText('concrete')).toBeInTheDocument()
    expect(screen.getAllByText('AI-read')).toHaveLength(2)
    fireEvent.click(toggle)
    expect(screen.queryByText('Slab 200mm')).toBeNull()
  })
})
