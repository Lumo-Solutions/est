// Typed fetch wrapper: same-origin /api/v1 base (proxied to the backend by
// Vite in dev, by nginx in the built image -- see vite.config.ts and
// Dockerfile), CSRF double-submit header injection, RFC 9457 problem-details
// parsing, and step-up-required interception. See
// docs/module-frontend-phase8-plan.md §0 for the server-side contract this
// implements against.

const API_BASE = '/api/v1'
const CSRF_COOKIE_NAME = '__Host-ins_csrf' // app/security/cookies.py::CSRF_COOKIE
const CSRF_HEADER_NAME = 'X-CSRF-Token' // app/core/config.py::Settings.csrf_header default
const STEP_UP_ERROR_TYPE = 'urn:installtec:step-up-required' // app/core/errors.py::StepUpRequiredError

export interface ProblemDetails {
  type: string
  title: string
  status: number
  detail?: string
  instance?: string
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly problem: ProblemDetails

  constructor(status: number, problem: ProblemDetails) {
    super(problem.detail || problem.title || `Request failed (${status})`)
    this.status = status
    this.problem = problem
  }

  get isStepUpRequired(): boolean {
    return this.problem.type === STEP_UP_ERROR_TYPE
  }
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

function currentLocation(): string {
  return window.location.pathname + window.location.search
}

export function loginUrl(next: string = currentLocation()): string {
  return `${API_BASE}/auth/login?next=${encodeURIComponent(next)}`
}

function stepUpUrl(next: string = currentLocation()): string {
  return `${API_BASE}/auth/step-up?next=${encodeURIComponent(next)}`
}

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined

  if (opts.body instanceof FormData) {
    // Let the browser set Content-Type itself (multipart boundary) --
    // JSON.stringify-ing a FormData produces "{}" and silently drops the file.
    body = opts.body
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  if (!SAFE_METHODS.has(method)) {
    headers[CSRF_HEADER_NAME] = readCookie(CSRF_COOKIE_NAME)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    credentials: 'same-origin',
    signal: opts.signal,
  })

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('json') ? await response.json() : undefined

  if (!response.ok) {
    const problem: ProblemDetails = payload ?? {
      type: 'about:blank',
      title: response.statusText,
      status: response.status,
    }
    const error = new ApiError(response.status, problem)
    if (error.isStepUpRequired) {
      window.location.href = stepUpUrl()
    }
    throw error
  }

  return payload as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'GET', signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: 'POST', body, signal }),
  put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: 'PUT', body, signal }),
  patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: 'PATCH', body, signal }),
  delete: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'DELETE', signal }),
}

function filenameFromContentDisposition(header: string | null, fallback: string): string {
  const match = header?.match(/filename="?([^"]+)"?/)
  return match ? match[1] : fallback
}

/** For endpoints that return a raw file (xlsx export) instead of JSON --
 * e.g. POST /bid-settlements/{id}/export -- bypasses the JSON-only
 * `request()` above. Triggers a real browser download via a temporary
 * object URL. */
export async function downloadFile(path: string, body: unknown, fallbackFilename: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', [CSRF_HEADER_NAME]: readCookie(CSRF_COOKIE_NAME) },
    body: JSON.stringify(body ?? {}),
    credentials: 'same-origin',
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''
    const payload = contentType.includes('json') ? await response.json() : undefined
    const problem: ProblemDetails = payload ?? { type: 'about:blank', title: response.statusText, status: response.status }
    const error = new ApiError(response.status, problem)
    if (error.isStepUpRequired) window.location.href = stepUpUrl()
    throw error
  }

  const blob = await response.blob()
  const filename = filenameFromContentDisposition(response.headers.get('content-disposition'), fallbackFilename)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: { [CSRF_HEADER_NAME]: readCookie(CSRF_COOKIE_NAME) },
      credentials: 'same-origin',
    })
  } catch {
    // Best-effort RP-initiated Keycloak logout via the redirect chain; our
    // own session cookie is cleared by the first hop regardless of whether
    // the rest of the chain completes from here.
  }
  window.location.href = '/'
}
