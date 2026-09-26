import { useRef } from 'react'
import { useUploadDrawing } from './api'

export function DrawingUpload({ projectId }: { projectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useUploadDrawing(projectId)

  return (
    <div className="mb-4 flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.dxf,application/pdf,application/dxf,image/vnd.dxf"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) upload.mutate(file)
        }}
        className="text-sm"
      />
      {upload.isPending && <span className="text-sm text-slate-500">Uploading...</span>}
      {upload.isError && <span className="text-sm text-red-600">{upload.error.message}</span>}
      {upload.isSuccess && (
        <span className="text-sm text-green-700">Uploaded -- extraction queued.</span>
      )}
    </div>
  )
}
