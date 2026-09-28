import { useId, useRef } from 'react'
import { useUploadDrawing } from './api'

export function DrawingUpload({ projectId }: { projectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useUploadDrawing(projectId)
  const inputId = useId()

  return (
    <div className="mb-4 flex items-center gap-2">
      <label htmlFor={inputId} className="text-sm text-slate-600">
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
        className="text-sm"
      />
      {upload.isPending && <span className="text-sm text-slate-500">Uploading...</span>}
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
