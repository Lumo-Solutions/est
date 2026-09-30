import { useRef, useState } from 'react'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { DropZone, type PathedFile } from '../../components/DropZone'
import { TextField } from '../../components/Field'
import { useAddTenderFiles, useCreateTenderPackage } from './api'
import { MAX_FILE_BYTES, formatBytes, splitIntoBatches, todayIso } from './lib'

// Upload in batches (<= 20 files / 200 MB per request, matching the backend
// limits). The first batch creates the package; the rest are added to it.
//
// `hero` is the empty-project look: one big drop target with Choose folder / Choose files buttons and
// the label, ref and date fields folded away under "Upload details". `compact` is the plain card.
export function UploadPanel({
  projectId,
  onUploaded,
  variant = 'compact',
}: {
  projectId: string
  onUploaded: (packageId: string) => void
  variant?: 'hero' | 'compact'
}) {
  const hero = variant === 'hero'
  const dropRef = useRef<HTMLDivElement>(null)
  // The hero buttons drive the DropZone's own (visually hidden) inputs, so its batching and folder
  // handling are reused as they are.
  const openInput = (testId: string) => dropRef.current?.querySelector<HTMLInputElement>(`[data-testid="${testId}"]`)?.click()
  const [label, setLabel] = useState(`Transmittal ${todayIso()}`)
  const [ref, setRef] = useState('')
  const [received, setReceived] = useState(todayIso())
  const [files, setFiles] = useState<File[]>([])
  const [rejected, setRejected] = useState<string[]>([])
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Set after the first batch created the package, so a retry continues in the same package.
  const [resumePackageId, setResumePackageId] = useState<string | null>(null)
  const [uploadedSoFar, setUploadedSoFar] = useState(0)
  const create = useCreateTenderPackage(projectId)
  const addFiles = useAddTenderFiles(undefined, projectId)

  const onFiles = (chosen: File[]) => {
    const tooBig = chosen.filter((f) => f.size > MAX_FILE_BYTES)
    setRejected(tooBig.map((f) => `${f.name} is ${formatBytes(f.size)}: larger than the 60 MB per-file limit, so it was not added.`))
    const ok = chosen.filter((f) => f.size <= MAX_FILE_BYTES)
    setFiles((prev) => [...prev, ...ok])
    setError(null)
    setProgress(null)
  }

  const upload = async () => {
    setBusy(true)
    setError(null)
    const batches = splitIntoBatches(files)
    const total = files.length + uploadedSoFar
    let done = uploadedSoFar
    let packageId = resumePackageId
    let remaining = files
    setProgress(`Uploaded ${done} of ${total} files`)
    try {
      for (const batch of batches) {
        if (packageId === null) {
          const first = await create.mutateAsync({
            files: batch,
            label: label.trim() || undefined,
            transmittal_ref: ref.trim() || undefined,
            received_date: received || undefined,
          })
          packageId = first.package_id
          setResumePackageId(packageId)
        } else {
          await addFiles.mutateAsync({ files: batch, packageId })
        }
        done += batch.length
        remaining = remaining.slice(batch.length)
        // Sent files leave the list at once, so a retry after an error only re-sends what is left.
        setFiles(remaining)
        setUploadedSoFar(done)
        setProgress(`Uploaded ${done} of ${total} files`)
      }
      setRejected([])
      setResumePackageId(null)
      setUploadedSoFar(0)
      onUploaded(packageId as string)
    } catch (e) {
      setError(
        `${e instanceof Error ? e.message : 'Upload failed'}. ${done} of ${total} files were uploaded; ${remaining.length} still to send. Press Upload to continue with the rest.`,
      )
    } finally {
      setBusy(false)
    }
  }

  const fields = (
    <div className="grid gap-4 md:grid-cols-3">
      <TextField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} disabled={busy} />
      <TextField label="Transmittal ref (optional)" value={ref} onChange={(e) => setRef(e.target.value)} disabled={busy} />
      <TextField label="Received date" type="date" value={received} onChange={(e) => setReceived(e.target.value)} disabled={busy} />
    </div>
  )

  const queue = (
    <>
      {rejected.length > 0 && (
        <ul role="alert" className="mt-3 space-y-1 text-sm text-danger">
          {rejected.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <div className="mt-4">
          <ul aria-label="Files to upload" className="max-h-48 divide-y divide-row-rule overflow-y-auto text-sm text-ink">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex justify-between gap-4 py-1.5">
                <span className="truncate">{(f as PathedFile).relativePath ?? f.name}</span>
                <span className="shrink-0 tabular-nums text-ink-2">{formatBytes(f.size)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center gap-3">
            <Button onClick={upload} loading={busy}>
              Upload {files.length} {files.length === 1 ? 'file' : 'files'}
            </Button>
            <Button variant="secondary" onClick={() => setFiles([])} disabled={busy}>
              Clear list
            </Button>
          </div>
        </div>
      )}
      {progress && (
        <p role="status" className="mt-3 text-sm text-ink-2">
          {progress}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
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
            <p className="mt-3 text-xs text-ink-2">PDF, DXF, DWG, XLSX, DOCX, images or a .zip; up to 60 MB per file</p>
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
