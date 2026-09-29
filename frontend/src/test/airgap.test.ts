import { describe, expect, it } from 'vitest'

// docs/figma-implementation-plan.md 6 -- the app is air-gapped: fonts and
// icons are bundled, and no source file may reference a remote asset or CDN
// (Figma's own asset URLs are 7-day remote links; a pasted one would work in
// dev and silently break offline). Scans every source file's raw text.
const sources = import.meta.glob(['../**/*.ts', '../**/*.tsx', '../**/*.css'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const FORBIDDEN_HOSTS = [
  'figma.com',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'cdnjs.cloudflare.com',
  'cdn.jsdelivr.net',
  'unpkg.com',
  'githubusercontent.com',
]

// Namespace URIs and local addresses are not network fetches.
const ALLOWED = [/^https?:\/\/www\.w3\.org\//, /^https?:\/\/localhost(:\d+)?/, /^https?:\/\/127\.0\.0\.1/]

describe('air-gap guard', () => {
  const entries = Object.entries(sources).filter(([path]) => !path.endsWith('airgap.test.ts'))

  it('scans a meaningful number of source files', () => {
    expect(entries.length).toBeGreaterThan(40)
  })

  it.each(FORBIDDEN_HOSTS)('no source file references %s', (host) => {
    const hits = entries.filter(([, text]) => text.includes(host)).map(([path]) => path)
    expect(hits).toEqual([])
  })

  it('no source file contains a remote http(s) URL outside the allowlist', () => {
    const hits: string[] = []
    for (const [path, text] of entries) {
      // Test files may assert against example URLs; app code may not embed them.
      if (/\.test\.tsx?$/.test(path)) continue
      for (const m of text.matchAll(/https?:\/\/[^\s'"`)>]+/g)) {
        if (!ALLOWED.some((re) => re.test(m[0]))) hits.push(`${path}: ${m[0]}`)
      }
    }
    expect(hits).toEqual([])
  })
})
