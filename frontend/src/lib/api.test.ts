import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, loginUrl } from './api'

function mockFetchOnce(response: Partial<Response> & { jsonBody?: unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    statusText: response.statusText ?? 'OK',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => response.jsonBody,
  } as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api client', () => {
  beforeEach(() => {
    document.cookie = '__Host-ins_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the CSRF header (read from the double-submit cookie) on mutating requests', async () => {
    document.cookie = '__Host-ins_csrf=test-token; Secure; Path=/'
    const fetchMock = mockFetchOnce({ jsonBody: { ok: true } })

    await api.post('/projects', { name: 'x' })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-CSRF-Token']).toBe('test-token')
  })

  it('omits the CSRF header on safe (GET) requests', async () => {
    const fetchMock = mockFetchOnce({ jsonBody: { ok: true } })

    await api.get('/projects')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('throws an ApiError carrying the parsed problem-details body on failure', async () => {
    mockFetchOnce({
      ok: false,
      status: 404,
      jsonBody: { type: 'urn:installtec:not-found', title: 'Resource not found', status: 404, detail: 'no such project' },
    })

    await expect(api.get('/projects/does-not-exist')).rejects.toMatchObject({
      status: 404,
      message: 'no such project',
    })
  })

  it('redirects to step-up and still throws when the server reports step-up-required', async () => {
    mockFetchOnce({
      ok: false,
      status: 403,
      jsonBody: { type: 'urn:installtec:step-up-required', title: 'Re-authentication required', status: 403 },
    })
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      value: { ...originalLocation, href: '', pathname: '/projects/1', search: '' },
      writable: true,
    })

    const error = await api.get('/settlements/1/approve').catch((e) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isStepUpRequired).toBe(true)
    expect(window.location.href).toContain('/api/v1/auth/step-up?next=')
    Object.defineProperty(window, 'location', { value: originalLocation, writable: true })
  })
})

describe('loginUrl', () => {
  it('builds a same-origin login URL carrying the current path as next', () => {
    expect(loginUrl('/projects/abc')).toBe('/api/v1/auth/login?next=%2Fprojects%2Fabc')
  })
})
