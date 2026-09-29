import { useId, useRef } from 'react'
import { useUploadDrawing } from './api'

export function DrawingUpload({ projectId }: { projectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useUploadDrawing(projectId)
  const inputId = useId()

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <label htmlFor={inputId} className="text-base text-ink">
        Upload drawing (PDF or DXF)
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept=".pdf,.dxf,application/pdf,application/dxf,image/vnd.dxf"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) upload.mutate(file)
        }}
        className="text-sm text-ink file:mr-3 file:cursor-pointer file:rounded-pill file:border file:border-brand file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium file:text-brand hover:file:bg-brand-subtle"
      />
      {upload.isPending && <span className="text-sm text-muted">Uploading...</span>}
      {upload.isError && (
        <span role="alert" className="text-sm text-danger">
          {upload.error.message}
        </span>
      )}
      {upload.isSuccess && (
        <span role="status" className="text-sm text-emerald-700">
          Uploaded -- extraction queued.
        </span>
      )}
    </div>
  )
}
