import { useState } from 'react'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { DropZone } from '../../components/DropZone'
import { TextField } from '../../components/Field'
import { useAddTenderFiles, useCreateTenderPackage } from './api'
import { MAX_FILE_BYTES, formatBytes, splitIntoBatches, todayIso } from './lib'

// Upload in batches (<= 20 files / 200 MB per request, matching the backend
// limits). The first batch creates the package; the rest are added to it.
export function UploadPanel({ projectId, onUploaded }: { projectId: string; onUploaded: (packageId: string) => void }) {
  const [label, setLabel] = useState(`Transmittal ${todayIso()}`)
  const [ref, setRef] = useState('')
  const [received, setReceived] = useState(todayIso())
  const [files, setFiles] = useState<File[]>([])
  const [rejected, setRejected] = useState<string[]>([])
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
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
    const total = files.length
    let done = 0
    setProgress(`Uploaded 0 of ${total} files`)
    try {
      const first = await create.mutateAsync({
        files: batches[0],
        label: label.trim() || undefined,
        transmittal_ref: ref.trim() || undefined,
        received_date: received || undefined,
      })
      done += batches[0].length
      setProgress(`Uploaded ${done} of ${total} files`)
      for (const batch of batches.slice(1)) {
        await addFiles.mutateAsync({ files: batch, packageId: first.package_id })
        done += batch.length
        setProgress(`Uploaded ${done} of ${total} files`)
      }
      setFiles([])
      setRejected([])
      onUploaded(first.package_id)
    } catch (e) {
      setError(`${e instanceof Error ? e.message : 'Upload failed'} (${done} of ${total} files were uploaded before the error)`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mt-6">
      <SectionHeading>Upload tender documents</SectionHeading>
      <div className="grid gap-4 md:grid-cols-3">
        <TextField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} disabled={busy} />
        <TextField label="Transmittal ref (optional)" value={ref} onChange={(e) => setRef(e.target.value)} disabled={busy} />
        <TextField label="Received date" type="date" value={received} onChange={(e) => setReceived(e.target.value)} disabled={busy} />
      </div>
      <div className="mt-4">
        <DropZone label="Tender files" onFiles={onFiles} disabled={busy} />
      </div>
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
                <span className="truncate">{f.name}</span>
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
    </Card>
  )
}
