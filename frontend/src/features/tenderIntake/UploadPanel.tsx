import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '../../components/Button'
import { useInvalidateIntake } from './api'
import { Card, SectionHeading } from '../../components/Card'
import { DropZone, type PathedFile } from '../../components/DropZone'
import { TextField } from '../../components/Field'
import { MAX_FILE_BYTES, formatBytes, todayIso } from './lib'
import { STOPPED_BY_USER, pathOf, runUpload, type UploadOutcome, type UploadProgress } from './upload/uploader'

const PREVIEW_ROWS = 10
const LIST_CAP = 50
const PROGRESS_INTERVAL_MS = 250

const num = (n: number) => n.toLocaleString('en-US')

function formatTotal(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  return formatBytes(bytes)
}

function statusText(p: UploadProgress | null): string | null {
  if (!p) return null
  if (p.phase === 'hashing') return `Preparing ${num(p.done)} / ${num(p.total)}`
  if (p.phase === 'registering') return `Registering ${num(p.total)} files`
  const failed = p.failed > 0 ? ` (${num(p.failed)} failed)` : ''
  return `Uploaded ${num(p.uploaded)} / ${num(p.total)}${failed}`
}

function percent(p: UploadProgress): number {
  if (p.phase === 'hashing') return p.total ? (p.done / p.total) * 100 : 0
  if (p.phase === 'registering') return p.total ? (p.done / p.total) * 100 : 0
  return p.total ? (p.uploaded / p.total) * 100 : 0
}

// A bounded preview: the first few paths, never one row per file. Memoised so progress ticks do not touch it.
const FilePreview = memo(function FilePreview({ files }: { files: PathedFile[] }) {
  const shown = files.slice(0, PREVIEW_ROWS)
  return (
    <ul aria-label="Files to upload" className="divide-y divide-row-rule text-sm text-ink">
      {shown.map((f, i) => (
        <li key={`${pathOf(f)}-${i}`} className="flex justify-between gap-4 py-1.5">
          <span className="truncate">{pathOf(f)}</span>
          <span className="shrink-0 tabular-nums text-ink-2">{formatBytes(f.size)}</span>
        </li>
      ))}
      {files.length > shown.length && (
        <li className="py-1.5 text-ink-2">and {num(files.length - shown.length)} more</li>
      )}
    </ul>
  )
})

function CappedList({ items, render }: { items: string[]; render?: (s: string) => string }) {
  const shown = items.slice(0, LIST_CAP)
  return (
    <ul className="mt-2 space-y-1 text-sm">
      {shown.map((m, i) => (
        <li key={`${m}-${i}`}>{render ? render(m) : m}</li>
      ))}
      {items.length > shown.length && <li>and {num(items.length - shown.length)} more</li>}
    </ul>
  )
}

// Hash every file in the browser, register them with the server, then send only the bytes the server still needs
// (see ./upload/uploader.ts). Dropping the same folder again after a stop or a closed tab continues where it stopped.
//
// `hero` is the empty-project look: one big drop target with Choose folder / Choose files buttons and
// the label, ref and date fields folded away under "Upload details". `compact` is the plain card.
export function UploadPanel({
  projectId,
  onUploaded,
  onUploadStart,
  variant = 'compact',
}: {
  projectId: string
  onUploaded: (packageId: string) => void
  /** Fired when an upload begins, so a parent can keep this panel on screen until `onUploaded` or until the user leaves. */
  onUploadStart?: () => void
  variant?: 'hero' | 'compact'
}) {
  const hero = variant === 'hero'
  const dropRef = useRef<HTMLDivElement>(null)
  // The hero buttons drive the DropZone's own (visually hidden) inputs, so its folder handling is reused as it is.
  const openInput = (testId: string) => dropRef.current?.querySelector<HTMLInputElement>(`[data-testid="${testId}"]`)?.click()
  const [label, setLabel] = useState(`Transmittal ${todayIso()}`)
  const [ref, setRef] = useState('')
  const [received, setReceived] = useState(todayIso())
  const [files, setFiles] = useState<PathedFile[]>([])
  const [tooBig, setTooBig] = useState<string[]>([])
  const [progress, setProgress] = useState<UploadProgress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<UploadOutcome | null>(null)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const throttle = useRef<{ last: number; timer: ReturnType<typeof setTimeout> | null; pending: UploadProgress | null }>({
    last: 0,
    timer: null,
    pending: null,
  })

  useEffect(
    () => () => {
      abortRef.current?.abort()
      if (throttle.current.timer) clearTimeout(throttle.current.timer)
    },
    [],
  )

  const totalBytes = useMemo(() => files.reduce((s, f) => s + f.size, 0), [files])

  const pushProgress = (p: UploadProgress) => {
    const t = throttle.current
    t.pending = p
    const wait = PROGRESS_INTERVAL_MS - (Date.now() - t.last)
    if (wait <= 0) {
      t.last = Date.now()
      t.pending = null
      setProgress(p)
    } else if (!t.timer) {
      t.timer = setTimeout(() => {
        t.timer = null
        t.last = Date.now()
        if (t.pending) setProgress(t.pending)
        t.pending = null
      }, wait)
    }
  }

  const invalidate = useInvalidateIntake(projectId)
  const lastRefresh = useRef(0)

  const flushProgress = (p: UploadProgress | null) => {
    const t = throttle.current
    if (t.timer) clearTimeout(t.timer)
    t.timer = null
    t.pending = null
    setProgress(p)
  }

  const onFiles = (chosen: File[]) => {
    const big = chosen.filter((f) => f.size > MAX_FILE_BYTES)
    setTooBig(
      big.map((f) => `${pathOf(f)} is ${formatBytes(f.size)}: larger than the ${MAX_FILE_BYTES / (1024 * 1024)} MB per-file limit, so it was not added.`),
    )
    const ok = chosen.filter((f) => f.size <= MAX_FILE_BYTES)
    setFiles((prev) => [...prev, ...ok])
    setError(null)
    setNotice(null)
    setOutcome(null)
    flushProgress(null)
  }

  const upload = async () => {
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    onUploadStart?.()
    setError(null)
    setNotice(null)
    setOutcome(null)
    let last: UploadProgress | null = null
    try {
      const result = await runUpload({
        projectId,
        files,
        label: label.trim() || undefined,
        transmittal_ref: ref.trim() || undefined,
        received_date: received || undefined,
        signal: ac.signal,
        onProgress: (p) => {
          last = p
          pushProgress(p)
          // The project page's counts follow the upload (at most every 3 s), so the pack appears and fills in.
          if (p.phase === 'uploading' && Date.now() - lastRefresh.current > 3000) {
            lastRefresh.current = Date.now()
            invalidate()
          }
        },
        onRegistered: ({ resumed, alreadyUploaded }) => {
          invalidate()
          if (resumed) setNotice(`Continuing an unfinished upload: ${num(alreadyUploaded)} ${alreadyUploaded === 1 ? 'file was' : 'files were'} already here.`)
        },
      })
      flushProgress(last)
      setOutcome(result)
      if (result.stopped === STOPPED_BY_USER) {
        setNotice(result.stopped)
      } else if (result.stopped) {
        setError(result.stopped)
      } else if (result.packageId) {
        if (result.failed.length === 0) setFiles([])
        onUploaded(result.packageId)
      }
    } catch (e) {
      flushProgress(last)
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      abortRef.current = null
      setBusy(false)
      invalidate()
    }
  }

  const stop = () => abortRef.current?.abort()

  const fields = (
    <div className="grid gap-4 md:grid-cols-3">
      <TextField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} disabled={busy} />
      <TextField label="Transmittal ref (optional)" value={ref} onChange={(e) => setRef(e.target.value)} disabled={busy} />
      <TextField label="Received date" type="date" value={received} onChange={(e) => setReceived(e.target.value)} disabled={busy} />
    </div>
  )

  const status = statusText(progress)
  const queue = (
    <>
      {tooBig.length > 0 && (
        <div role="alert" className="mt-3 text-sm text-danger">
          <CappedList items={tooBig} />
        </div>
      )}
      {files.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-medium text-ink">
            {num(files.length)} {files.length === 1 ? 'file' : 'files'} ({formatTotal(totalBytes)}) ready
          </p>
          <FilePreview files={files} />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button onClick={upload} loading={busy} disabled={busy}>
              Upload {num(files.length)} {files.length === 1 ? 'file' : 'files'}
            </Button>
            {busy && (
              <Button variant="secondary" onClick={stop}>
                Stop
              </Button>
            )}
            <Button variant="secondary" onClick={() => setFiles([])} disabled={busy}>
              Clear list
            </Button>
          </div>
          {busy && (
            <p className="mt-2 text-xs text-ink-2">
              You can press Stop, or close this tab, at any time. Dropping the same folder again continues where it stopped.
            </p>
          )}
        </div>
      )}
      {progress && (
        <div className="mt-3">
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percent(progress))}
            className="h-2 w-full overflow-hidden rounded-full bg-row-rule"
          >
            <div className="h-full bg-brand transition-[width]" style={{ width: `${percent(progress)}%` }} />
          </div>
        </div>
      )}
      <p role="status" aria-live="polite" className="mt-2 text-sm text-ink-2">
        {status}
        {status && notice ? ' ' : ''}
        {notice}
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
      {outcome && outcome.rejected.length > 0 && (
        <details className="mt-3 text-sm text-ink">
          <summary className="cursor-pointer font-medium">
            {num(outcome.rejected.length)} {outcome.rejected.length === 1 ? 'file was' : 'files were'} not accepted
          </summary>
          <CappedList items={outcome.rejected.map((r) => `${r.path}: ${r.reason}`)} />
        </details>
      )}
      {outcome && outcome.failed.length > 0 && (
        <div role="alert" className="mt-3 text-sm text-danger">
          <p className="font-medium">
            {num(outcome.failed.length)} {outcome.failed.length === 1 ? 'file' : 'files'} could not be uploaded. Press Upload to try them again.
          </p>
          <CappedList items={outcome.failed.map((f) => `${f.path}: ${f.message}`)} />
        </div>
      )}
    </>
  )

  if (hero) {
    return (
      <div className="mt-6">
        <div className="relative min-h-[16rem] rounded-card bg-brand-subtle">
          {/* The DropZone fills the hero so a drop anywhere lands; its own inputs, labels and help text
              stay in the DOM for keyboard and screen-reader users but are visually hidden. */}
          <div
            ref={dropRef}
            className="absolute inset-0 [&>div]:h-full [&>div]:!border-brand [&>div]:!p-0 [&_input[type=file]]:sr-only [&_label]:sr-only [&_p[id]]:sr-only"
          >
            <DropZone label="Tender files" onFiles={onFiles} disabled={busy} />
          </div>
          <div className="pointer-events-none relative flex min-h-[16rem] flex-col items-center justify-center p-8 text-center">
            <h2 className="text-xl font-semibold text-ink">Drop your tender folder or zip here</h2>
            <p className="mx-auto mt-2 max-w-xl text-base text-ink-2">
              Every file is read, classified and sorted for you. Anything uncertain is listed for a quick check.
            </p>
            <div className="pointer-events-auto mt-4 flex flex-wrap justify-center gap-3">
              <Button disabled={busy} onClick={() => openInput('tender-folder-input')}>
                Choose folder
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => openInput('tender-file-input')}>
                Choose files
              </Button>
            </div>
            <p className="mt-3 text-xs text-ink-2">PDF, DXF, DWG, XLSX, DOCX, images or a .zip; up to 250 MB per file</p>
          </div>
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer rounded text-sm font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1">
            Upload details
          </summary>
          <div className="mt-3">{fields}</div>
        </details>
        {queue}
      </div>
    )
  }

  return (
    <Card className="mt-6">
      <SectionHeading>Upload tender documents</SectionHeading>
      {fields}
      <div className="mt-4">
        <DropZone label="Tender files" onFiles={onFiles} disabled={busy} />
      </div>
      {queue}
    </Card>
  )
}
