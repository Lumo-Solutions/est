import { afterEach, describe, expect, it, vi } from 'vitest'
import { logout } from './api'

// Sign-out must be a top-level form POST carrying the CSRF token as a field
// (never a fetch): only a real navigation follows the 303 chain through
// Keycloak's end-session endpoint and clears the browser's SSO cookies.
describe('logout', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('submits a POST form to /auth/logout with the csrf_token field and does not use fetch', () => {
    // jsdom (http) refuses to store a __Host- cookie, so stub the read instead.
    vi.spyOn(document, 'cookie', 'get').mockReturnValue('other=1; __Host-ins_csrf=csrf-123')
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})

    logout()

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(submit).toHaveBeenCalledTimes(1)
    const form = submit.mock.contexts[0] as HTMLFormElement
    expect(form.method.toLowerCase()).toBe('post')
    expect(form.getAttribute('action')).toBe('/api/v1/auth/logout')
    const field = form.querySelector('input[name="csrf_token"]') as HTMLInputElement
    expect(field.type).toBe('hidden')
    expect(field.value).toBe('csrf-123')
  })
})
