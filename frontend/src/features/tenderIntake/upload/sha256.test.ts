import { describe, expect, it } from 'vitest'
import { sha256Hex } from './sha256'

const EMPTY = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
const ABC = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'

async function reference(blob: Blob): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, '0')).join('')
}

function pattern(n: number): Uint8Array<ArrayBuffer> {
  const a = new Uint8Array(n)
  for (let i = 0; i < n; i++) a[i] = (i * 31 + 7) & 0xff
  return a
}

describe('sha256Hex', () => {
  it('matches known vectors on both paths', async () => {
    for (const smallLimit of [undefined, 0]) {
      expect(await sha256Hex(new Blob([]), { smallLimit })).toBe(EMPTY)
      expect(await sha256Hex(new Blob(['abc']), { smallLimit })).toBe(ABC)
    }
  })

  it('hashes a 1 MB pattern the same on both paths', async () => {
    const blob = new Blob([pattern(1024 * 1024)])
    const want = await reference(blob)
    expect(await sha256Hex(blob)).toBe(want)
    expect(await sha256Hex(blob, { smallLimit: 10 })).toBe(want)
  })

  it('incremental path matches crypto.subtle on a multi-slice blob with an odd length', async () => {
    const blob = new Blob([pattern(9 * 1024 * 1024 + 123)])
    const progress: number[] = []
    const got = await sha256Hex(blob, { smallLimit: 1024, onProgress: (f) => progress.push(f) })
    expect(got).toBe(await reference(blob))
    expect(progress.length).toBe(3)
    expect(progress.at(-1)).toBe(1)
  })

  it('handles lengths around the padding boundary', async () => {
    for (const n of [55, 56, 57, 63, 64, 65, 119, 120, 128]) {
      const blob = new Blob([pattern(n)])
      expect(await sha256Hex(blob, { smallLimit: 0 })).toBe(await reference(blob))
    }
  })

  it('rejects when aborted', async () => {
    const ac = new AbortController()
    ac.abort()
    await expect(sha256Hex(new Blob(['abc']), { signal: ac.signal })).rejects.toThrow()
    const ac2 = new AbortController()
    const blob = new Blob([pattern(9 * 1024 * 1024)])
    const p = sha256Hex(blob, { smallLimit: 0, signal: ac2.signal, onProgress: () => ac2.abort() })
    await expect(p).rejects.toMatchObject({ name: 'AbortError' })
  })
})
