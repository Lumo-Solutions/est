import type { PathedFile } from '../../../components/DropZone'
import { putDocumentContent, registerFiles } from '../uploadApi'
import type { RegisterPackageIn, RegisterPackageOut, UploadResult } from '../uploadApi'
import { sha256Hex } from './sha256'

export const REGISTER_BATCH = 500
export const HASH_CONCURRENCY = 2
export const UPLOAD_CONCURRENCY = 4
export const BACKOFF_MS = [500, 2000, 8000]

export type UploadProgress =
  | { phase: 'hashing'; done: number; total: number }
  | { phase: 'registering'; done: number; total: number }
  | { phase: 'uploading'; uploaded: number; total: number; failed: number }

export interface UploaderDeps {
  registerFiles: (projectId: string, body: RegisterPackageIn, signal?: AbortSignal) => Promise<RegisterPackageOut>
  putDocumentContent: (packageId: string, documentId: string, file: Blob, signal?: AbortSignal) => Promise<UploadResult>
  sleep: (ms: number, signal?: AbortSignal) => Promise<void>
  sha256: (file: Blob, opts?: { signal?: AbortSignal }) => Promise<string>
}

export interface RunUploadArgs {
  projectId: string
  files: PathedFile[]
  label?: string
  transmittal_ref?: string
  received_date?: string
  signal?: AbortSignal
  onProgress?: (p: UploadProgress) => void
  /** Called with the first register response, so the UI can show the "resumed" notice. */
  onRegistered?: (info: { packageId: string; resumed: boolean; alreadyUploaded: number }) => void
  deps?: Partial<UploaderDeps>
}

export interface UploadOutcome {
  packageId: string | null
  resumed: boolean
  uploaded: number
  rejected: { path: string; reason: string }[]
  failed: { path: string; message: string }[]
  /** Set when the run ended early: pack paused/cancelled (server message) or the user stopped it. */
  stopped?: string
}

const defaultSleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal?.aborted) return resolve()
    const t = setTimeout(done, ms)
    function done() {
      clearTimeout(t)
      signal?.removeEventListener('abort', done)
      resolve()
    }
    signal?.addEventListener('abort', done, { once: true })
  })

export const STOPPED_BY_USER = 'Upload stopped. Drop the same folder again to continue where it stopped.'

export const pathOf = (f: PathedFile): string => f.relativePath ?? f.name

function isAbort(e: unknown): boolean {
  return e instanceof Error && e.name === 'AbortError'
}

function statusOf(e: unknown): number | null {
  const s = (e as { status?: unknown } | null)?.status
  return typeof s === 'number' ? s : null
}

/** Run `count` tasks with at most `limit` in flight. `fn` returns false to stop handing out more work. */
async function pool(count: number, limit: number, fn: (i: number) => Promise<boolean | void>): Promise<void> {
  let next = 0
  let halted = false
  const worker = async () => {
    while (!halted && next < count) {
      const i = next++
      if ((await fn(i)) === false) halted = true
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, count) }, worker))
}

export async function runUpload(args: RunUploadArgs): Promise<UploadOutcome> {
  const { projectId, files, signal, onProgress } = args
  const deps: UploaderDeps = {
    registerFiles,
    putDocumentContent,
    sleep: defaultSleep,
    sha256: sha256Hex,
    ...args.deps,
  }
  const total = files.length
  const outcome: UploadOutcome = { packageId: null, resumed: false, uploaded: 0, rejected: [], failed: [] }
  const stoppedNow = () => signal?.aborted === true

  // (a) hash, two files at a time
  const shas: string[] = new Array(total)
  let hashed = 0
  onProgress?.({ phase: 'hashing', done: 0, total })
  try {
    await pool(total, HASH_CONCURRENCY, async (i) => {
      if (stoppedNow()) return false
      shas[i] = await deps.sha256(files[i], { signal })
      hashed++
      onProgress?.({ phase: 'hashing', done: hashed, total })
    })
  } catch (e) {
    if (isAbort(e) || stoppedNow()) return { ...outcome, stopped: STOPPED_BY_USER }
    throw e
  }
  if (stoppedNow()) return { ...outcome, stopped: STOPPED_BY_USER }

  // (b) register in batches; only the files that need bytes are kept (index + document id).
  const toSend: { index: number; documentId: string }[] = []
  let baseline = 0 // files already on the server or refused: counted as done
  let packageId: string | null = null
  let first = true
  try {
    for (let start = 0; start < total; start += REGISTER_BATCH) {
      if (stoppedNow()) return { ...outcome, stopped: STOPPED_BY_USER }
      const end = Math.min(start + REGISTER_BATCH, total)
      const byPath = new Map<string, number[]>()
      const batch = []
      for (let i = start; i < end; i++) {
        const path = pathOf(files[i])
        batch.push({ path, size: files[i].size, sha256: shas[i] })
        const q = byPath.get(path)
        if (q) q.push(i)
        else byPath.set(path, [i])
      }
      onProgress?.({ phase: 'registering', done: start, total })
      const res = await deps.registerFiles(
        projectId,
        {
          package_id: packageId,
          label: args.label || undefined,
          transmittal_ref: args.transmittal_ref || undefined,
          received_date: args.received_date || undefined,
          total_files: total,
          files: batch,
        },
        signal,
      )
      packageId = res.package_id
      outcome.packageId = packageId
      let uploadedHere = 0
      for (const f of res.files) {
        const idx = byPath.get(f.path)?.shift()
        if (f.state === 'rejected') {
          baseline++
          outcome.rejected.push({ path: f.path, reason: f.reason ?? 'Not accepted' })
        } else if (f.state === 'uploaded') {
          baseline++
          uploadedHere++
        } else if (f.upload && f.document_id && idx !== undefined) {
          toSend.push({ index: idx, documentId: f.document_id })
        }
      }
      if (first) {
        first = false
        outcome.resumed = res.resumed
        args.onRegistered?.({ packageId, resumed: res.resumed, alreadyUploaded: uploadedHere })
      }
    }
  } catch (e) {
    if (isAbort(e) || stoppedNow()) return { ...outcome, stopped: STOPPED_BY_USER }
    throw e
  }
  if (packageId === null) return outcome
  const pkg: string = packageId

  // (c) upload, four at a time, each retried with backoff
  let local = 0
  let serverSeen = 0
  let shown = Math.min(total, baseline)
  const emit = () => {
    // Monotonic: the number shown never goes down, whichever counter is ahead.
    shown = Math.max(shown, Math.min(total, Math.max(baseline + local, serverSeen)))
    onProgress?.({ phase: 'uploading', uploaded: shown, total, failed: outcome.failed.length })
  }
  emit()

  const sendOne = async (n: number): Promise<boolean> => {
    if (outcome.stopped || stoppedNow()) {
      outcome.stopped ??= STOPPED_BY_USER
      return false
    }
    const { index, documentId } = toSend[n]
    const file = files[index]
    for (let attempt = 0; ; attempt++) {
      try {
        const r = await deps.putDocumentContent(pkg, documentId, file, signal)
        local++
        if (typeof r?.uploaded === 'number') serverSeen = Math.max(serverSeen, r.uploaded + outcome.rejected.length)
        emit()
        return true
      } catch (e) {
        if (isAbort(e) || stoppedNow()) {
          outcome.stopped ??= STOPPED_BY_USER
          return false
        }
        const status = statusOf(e)
        const message = e instanceof Error ? e.message : 'Upload failed'
        if (status === 409) {
          outcome.stopped = message
          return false
        }
        // A 4xx other than 409 will not get better by retrying; network errors and 5xx do.
        if ((status !== null && status >= 400 && status < 500) || attempt >= BACKOFF_MS.length) {
          outcome.failed.push({ path: pathOf(file), message })
          emit()
          return true
        }
        await deps.sleep(BACKOFF_MS[attempt], signal)
        if (stoppedNow()) {
          outcome.stopped ??= STOPPED_BY_USER
          return false
        }
      }
    }
  }

  await pool(toSend.length, UPLOAD_CONCURRENCY, sendOne)

  // (d) final count. Files whose bytes match another file in the drop complete along with it.
  if (!outcome.stopped) shown = Math.max(shown, total - outcome.failed.length)
  outcome.uploaded = shown
  onProgress?.({ phase: 'uploading', uploaded: shown, total, failed: outcome.failed.length })
  return outcome
}
