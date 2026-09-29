import { useId, useRef, useState } from 'react'

export const DROPZONE_ACCEPT = '.pdf,.dxf,.dwg,.xlsx,.xls,.csv,.docx,.doc,.jpg,.jpeg,.png,.zip'
export const DROPZONE_HELP =
  'PDF, DXF, DWG, XLSX, XLS, CSV, DOCX, DOC, JPG, PNG or a .zip of them; up to 60 MB per file'

// Keyboard-accessible multi-file drop zone. The real <input type=file multiple>
// is visible and label-associated, so keyboard and screen-reader users get the
// native browse flow; drag-and-drop is an enhancement on the same region.
export function DropZone({
  label,
  accept = DROPZONE_ACCEPT,
  onFiles,
  disabled = false,
  help = DROPZONE_HELP,
}: {
  label: string
  accept?: string
  onFiles: (files: File[]) => void
  disabled?: boolean
  help?: string
}) {
  const inputId = useId()
  const helpId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <div
      role="group"
      aria-label={label}
      aria-describedby={helpId}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (disabled) return
        const files = Array.from(e.dataTransfer?.files ?? [])
        if (files.length > 0) onFiles(files)
      }}
      className={`rounded-card border-2 border-dashed p-5 transition-colors duration-150 ${
        dragging ? 'border-brand bg-brand-subtle' : 'border-hairline bg-canvas'
      } ${disabled ? 'opacity-60' : ''}`}
    >
      <label htmlFor={inputId} className="block text-base font-medium text-ink">
        {label}
      </label>
      <p id={helpId} className="mt-1 text-sm text-ink-2">
        Drag files here or choose them below. {help}.
      </p>
      <input
        ref={inputRef}
        id={inputId}
        data-testid="tender-file-input"
        type="file"
        multiple
        accept={accept}
        disabled={disabled}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length > 0) onFiles(files)
          // Allow choosing the same files again after a clear.
          e.target.value = ''
        }}
        className="mt-3 block text-sm text-ink file:mr-3 file:cursor-pointer file:rounded-pill file:border file:border-brand file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium file:text-brand hover:file:bg-brand-subtle"
      />
    </div>
  )
}
