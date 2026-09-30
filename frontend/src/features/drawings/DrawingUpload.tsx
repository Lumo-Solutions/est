import { useId, useRef } from 'react'
import { useUploadDrawings } from './api'

// Shown next to the picker and reused in tests/e2e: what the Drawings upload accepts.
export const ACCEPTED_DRAWING_TYPES_TEXT = 'PDF (vector), DXF, DWG (auto-converted)'

const ACCEPT = '.pdf,.dxf,.dwg,application/pdf,application/dxf,image/vnd.dxf,application/acad,image/vnd.dwg'

export function DrawingUpload({ projectId }: { projectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useUploadDrawings(projectId)
  const inputId = useId()
  const hintId = useId()
  const failed = upload.data?.filter((o) => !o.ok) ?? []
  const succeeded = upload.data?.filter((o) => o.ok) ?? []

  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={inputId} className="text-base text-ink">
          Upload drawings
        </label>
        <input
          ref={inputRef}
          id={inputId}
          data-testid="drawing-file-input"
          type="file"
          multiple
          accept={ACCEPT}
          aria-describedby={hintId}
          onChange={(e) => {
            const input = e.target
            const files = Array.from(input.files ?? [])
            if (files.length > 0) upload.mutate(files)
            // Let the same file be chosen again after a failure.
            input.value = ''
          }}
          className="text-sm text-ink file:mr-3 file:cursor-pointer file:rounded-pill file:border file:border-brand file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium file:text-brand hover:file:bg-brand-subtle"
        />
        {upload.isPending && <span className="text-sm text-muted">Uploading...</span>}
      </div>
      <p id={hintId} className="mt-1 text-sm text-muted">
        Accepted: {ACCEPTED_DRAWING_TYPES_TEXT}. Select several files at once.
      </p>
      {upload.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {upload.error.message}
        </p>
      )}
      {failed.length > 0 && (
        <ul role="alert" className="mt-1 text-sm text-danger">
          {failed.map((o) => (
            <li key={o.filename}>
              {o.filename}: {o.error}
            </li>
          ))}
        </ul>
      )}
      {succeeded.length > 0 && (
        <p role="status" className="mt-1 text-sm text-emerald-700">
          {succeeded.length === 1
            ? `Uploaded ${succeeded[0].filename} -- extraction queued.`
            : `Uploaded ${succeeded.length} files -- extraction queued.`}
        </p>
      )}
    </div>
  )
}
