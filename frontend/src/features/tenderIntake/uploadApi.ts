import { ApiError, api, type ProblemDetails } from '../../lib/api'

// Resumable upload endpoints (docs/intake-scale/api-contract.md, "Upload (resumable)").
// Mirrors backend/app/schemas/tender_intake.py: RegisterPackageIn / RegisterPackageOut / UploadResult.

const API_BASE = '/api/v1'
const CSRF_COOKIE_NAME = '__Host-ins_csrf' // same cookie lib/api.ts reads
const CSRF_HEADER_NAME = 'X-CSRF-Token'

export interface RegisterFileIn {
  path: string
  size: number
  sha256: string
}

export interface RegisterPackageIn {
  package_id?: string | null
  new_package?: boolean
  label?: string | null
  transmittal_ref?: string | null
  received_date?: string | null
  total_files?: number | null
  files: RegisterFileIn[]
}

export interface RegisteredFile {
  path: string
  sha256: string
  document_id: string | null
  /** pending | uploaded | same_as_another | rejected */
  state: string
  /** true: send this file's bytes */
  upload: boolean
  reason: string | null
}

export interface RegisterPackageOut {
  package_id: string
  status: string
  resumed: boolean
  expected_count: number | null
  files: RegisteredFile[]
}

export interface UploadResult {
  document_id: string
  state: string
  package_status: string
  registered: number
  uploaded: number
  expected_count: number | null
}

export function registerFiles(projectId: string, body: RegisterPackageIn, signal?: AbortSignal): Promise<RegisterPackageOut> {
  return api.post<RegisterPackageOut>(`/projects/${projectId}/tender-packages/register`, body, signal)
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

/** Raw-body PUT of one file (the browser streams the Blob; it is never read into JS memory). */
export async function putDocumentContent(
  packageId: string,
  documentId: string,
  file: Blob,
  signal?: AbortSignal,
): Promise<UploadResult> {
  const response = await fetch(`${API_BASE}/tender-packages/${packageId}/documents/${documentId}/content`, {
    method: 'PUT',
    body: file,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/octet-stream', [CSRF_HEADER_NAME]: readCookie(CSRF_COOKIE_NAME) },
    signal,
  })
  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('json') ? await response.json() : undefined
  if (!response.ok) {
    const problem: ProblemDetails = payload ?? {
      type: 'about:blank',
      title: response.statusText,
      status: response.status,
    }
    throw new ApiError(response.status, problem)
  }
  return payload as UploadResult
}
