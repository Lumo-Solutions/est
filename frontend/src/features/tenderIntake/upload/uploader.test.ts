import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../lib/api'
import type { RegisterPackageIn, RegisterPackageOut, RegisteredFile, UploadResult } from '../uploadApi'
import { runUpload, type UploaderDeps, type UploadProgress } from './uploader'

function makeFiles(n: number): File[] {
  return Array.from({ length: n }, (_, i) => new File(['x'], `f${i}.pdf`))
}

const problem = (status: number, detail: string) => new ApiError(status, { type: 'about:blank', title: 'x', status, detail })

interface Opts {
  already?: Set<string>
  rejected?: Set<string>
  resumed?: boolean
  put?: UploaderDeps['putDocumentContent']
}

function makeDeps(opts: Opts = {}) {
  const registerCalls: RegisterPackageIn[] = []
  const puts: string[] = []
  let inFlight = 0
  let maxInFlight = 0
  let uploaded = 0
  const deps: UploaderDeps = {
    sha256: async (f) => `sha-${(f as File).name}`,
    sleep: async () => {},
    registerFiles: async (_p, body): Promise<RegisterPackageOut> => {
      registerCalls.push(body)
      const files: RegisteredFile[] = body.files.map((f) => {
        const base = { path: f.path, sha256: f.sha256, reason: null }
        if (opts.rejected?.has(f.path)) return { ...base, document_id: null, state: 'rejected', upload: false, reason: 'Not a tender file' }
        if (opts.already?.has(f.path)) return { ...base, document_id: `d-${f.path}`, state: 'uploaded', upload: false }
        return { ...base, document_id: `d-${f.path}`, state: 'pending', upload: true }
      })
      return { package_id: 'pk1', status: 'uploading', resumed: opts.resumed ?? false, expected_count: null, files }
    },
    putDocumentContent: async (pk, docId, file, signal): Promise<UploadResult> => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      try {
        await new Promise((r) => setTimeout(r, 1))
        if (opts.put) return await opts.put(pk, docId, file, signal)
        puts.push(docId)
        uploaded++
        return { document_id: docId, state: 'uploaded', package_status: 'uploading', registered: 0, uploaded, expected_count: null }
      } finally {
        inFlight--
      }
    },
  }
  return { deps, registerCalls, puts, max: () => maxInFlight }
}

const base = { projectId: 'p1', label: 'L' }

describe('runUpload', () => {
  it('registers in batches of 500 with total_files and the first package id, then uploads all', async () => {
    const t = makeDeps()
    const out = await runUpload({ ...base, files: makeFiles(1200), deps: t.deps })
    expect(t.registerCalls.map((c) => c.files.length)).toEqual([500, 500, 200])
    expect(t.registerCalls.every((c) => c.total_files === 1200)).toBe(true)
    expect(t.registerCalls.map((c) => c.package_id)).toEqual([null, 'pk1', 'pk1'])
    expect(t.puts).toHaveLength(1200)
    expect(out).toMatchObject({ packageId: 'pk1', uploaded: 1200, failed: [], rejected: [] })
  }, 30_000)

  it('uses relativePath as the path and sends the hash', async () => {
    const t = makeDeps()
    const f = Object.assign(new File(['x'], 'a.pdf'), { relativePath: 'Dir/a.pdf' })
    await runUpload({ ...base, files: [f], deps: t.deps })
    expect(t.registerCalls[0].files[0]).toEqual({ path: 'Dir/a.pdf', size: 1, sha256: 'sha-a.pdf' })
  })

  it('resume: sends only upload:true files and reports the resumed flag', async () => {
    const files = makeFiles(10)
    const t = makeDeps({ already: new Set(files.slice(0, 7).map((f) => f.name)), resumed: true })
    const seen: unknown[] = []
    const out = await runUpload({ ...base, files, deps: t.deps, onRegistered: (i) => seen.push(i) })
    expect(t.puts).toEqual(['d-f7.pdf', 'd-f8.pdf', 'd-f9.pdf'])
    expect(out.resumed).toBe(true)
    expect(out.uploaded).toBe(10)
    expect(seen).toEqual([{ packageId: 'pk1', resumed: true, alreadyUploaded: 7 }])
  })

  it('collects rejected files with their reason and does not upload them', async () => {
    const t = makeDeps({ rejected: new Set(['f1.pdf']) })
    const out = await runUpload({ ...base, files: makeFiles(3), deps: t.deps })
    expect(out.rejected).toEqual([{ path: 'f1.pdf', reason: 'Not a tender file' }])
    expect(t.puts).toEqual(['d-f0.pdf', 'd-f2.pdf'])
  })

  it('retries network errors and 5xx with backoff, then succeeds', async () => {
    const sleeps: number[] = []
    let calls = 0
    const t = makeDeps({
      put: async (_p, docId) => {
        calls++
        if (calls === 1) throw new TypeError('network down')
        if (calls === 2) throw problem(502, 'bad gateway')
        return { document_id: docId, state: 'uploaded', package_status: 'uploading', registered: 1, uploaded: 1, expected_count: 1 }
      },
    })
    t.deps.sleep = async (ms) => {
      sleeps.push(ms)
    }
    const out = await runUpload({ ...base, files: makeFiles(1), deps: t.deps })
    expect(calls).toBe(3)
    expect(sleeps).toEqual([500, 2000])
    expect(out.failed).toEqual([])
    expect(out.uploaded).toBe(1)
  })

  it('gives up on a file after 3 retries and carries on with the rest', async () => {
    const sleeps: number[] = []
    const t = makeDeps({
      put: async (_p, docId) => {
        if (docId === 'd-f0.pdf') throw problem(503, 'unavailable')
        return { document_id: docId, state: 'uploaded', package_status: 'uploading', registered: 2, uploaded: 1, expected_count: 2 }
      },
    })
    t.deps.sleep = async (ms) => {
      sleeps.push(ms)
    }
    const out = await runUpload({ ...base, files: makeFiles(2), deps: t.deps })
    expect(sleeps).toEqual([500, 2000, 8000])
    expect(out.failed).toEqual([{ path: 'f0.pdf', message: 'unavailable' }])
    expect(out.uploaded).toBe(1)
  })

  it('a 422 fails that file without retrying', async () => {
    const sleep = vi.fn(async () => {})
    let calls = 0
    const t = makeDeps({
      put: async () => {
        calls++
        throw problem(422, 'Digest does not match')
      },
    })
    t.deps.sleep = sleep
    const out = await runUpload({ ...base, files: makeFiles(2), deps: t.deps })
    expect(calls).toBe(2)
    expect(sleep).not.toHaveBeenCalled()
    expect(out.failed.map((f) => f.message)).toEqual(['Digest does not match', 'Digest does not match'])
  })

  it('a 409 stops everything and returns the server message', async () => {
    let calls = 0
    const t = makeDeps({
      put: async () => {
        calls++
        throw problem(409, 'This pack is paused.')
      },
    })
    const out = await runUpload({ ...base, files: makeFiles(50), deps: t.deps })
    expect(out.stopped).toBe('This pack is paused.')
    expect(calls).toBeLessThanOrEqual(4)
    expect(out.failed).toEqual([])
  })

  it('never has more than 4 uploads in flight', async () => {
    const t = makeDeps()
    await runUpload({ ...base, files: makeFiles(40), deps: t.deps })
    expect(t.max()).toBeLessThanOrEqual(4)
    expect(t.max()).toBeGreaterThan(1)
  })

  it('progress is monotonic and ends at the total', async () => {
    const t = makeDeps()
    const events: UploadProgress[] = []
    await runUpload({ ...base, files: makeFiles(30), deps: t.deps, onProgress: (p) => events.push(p) })
    const hashing = events.filter((e) => e.phase === 'hashing').map((e) => (e as { done: number }).done)
    const uploading = events.filter((e) => e.phase === 'uploading').map((e) => (e as { uploaded: number }).uploaded)
    expect(hashing).toEqual([...hashing].sort((a, b) => a - b))
    expect(hashing.at(-1)).toBe(30)
    expect(uploading).toEqual([...uploading].sort((a, b) => a - b))
    expect(uploading.at(-1)).toBe(30)
    // Phases come in order.
    const phases = events.map((e) => e.phase)
    expect(phases.indexOf('uploading')).toBeGreaterThan(phases.lastIndexOf('hashing'))
  })

  it('abort stops the run and reports it as stopped', async () => {
    const ac = new AbortController()
    const t = makeDeps()
    const out = await runUpload({
      ...base,
      files: makeFiles(100),
      deps: t.deps,
      signal: ac.signal,
      onProgress: (p) => {
        if (p.phase === 'uploading' && p.uploaded >= 5) ac.abort()
      },
    })
    expect(out.stopped).toMatch(/Drop the same folder again/)
    expect(t.puts.length).toBeLessThan(100)
  })

  it('lets a register error (pack limit) reject with the server message', async () => {
    const t = makeDeps()
    t.deps.registerFiles = async () => {
      throw problem(422, 'This folder has 3,500 files; the limit is 3,000.')
    }
    await expect(runUpload({ ...base, files: makeFiles(3), deps: t.deps })).rejects.toThrow('the limit is 3,000')
  })
})
