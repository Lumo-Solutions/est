import { useId, useRef, useState } from 'react'

export const DROPZONE_ACCEPT = '.pdf,.dxf,.dwg,.xlsx,.xls,.csv,.docx,.doc,.jpg,.jpeg,.png,.zip'
export const DROPZONE_HELP =
  'PDF, DXF, DWG, XLSX, XLS, CSV, DOCX, DOC, JPG, PNG or a .zip of them; up to 60 MB per file'

/** A File that came out of a folder keeps its path relative to the folder that was chosen or dropped. */
export type PathedFile = File & { relativePath?: string }

const JUNK_NAMES = new Set(['.ds_store', 'thumbs.db', 'desktop.ini'])

/** OS metadata droppings and empty files are skipped silently (counted in a note). */
function isJunkFile(f: File): boolean {
  const name = f.name.toLowerCase()
  return JUNK_NAMES.has(name) || name.startsWith('~$') || name.startsWith('._') || f.size === 0
}

function withPath(f: File, relativePath: string | undefined): PathedFile {
  if (relativePath && relativePath.includes('/')) return Object.assign(f, { relativePath })
  return f
}

function readEntryFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function readAllEntries(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = dir.createReader()
  const all: FileSystemEntry[] = []
  // readEntries returns batches (100 in Chromium); loop until it returns an empty batch.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
    if (batch.length === 0) break
    all.push(...batch)
  }
  return all
}

async function walkEntry(entry: FileSystemEntry, out: PathedFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await readEntryFile(entry as FileSystemFileEntry)
    out.push(withPath(file, entry.fullPath.replace(/^\/+/, '')))
  } else if (entry.isDirectory) {
    for (const child of await readAllEntries(entry as FileSystemDirectoryEntry)) await walkEntry(child, out)
  }
}

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
  const folderId = useId()
  const [dragging, setDragging] = useState(false)
  const [skipped, setSkipped] = useState(0)

  const deliver = (all: File[]) => {
    const kept = all.filter((f) => !isJunkFile(f))
    setSkipped(all.length - kept.length)
    if (kept.length > 0) onFiles(kept)
  }

  const onDropItems = (dt: DataTransfer) => {
    // Entries must be read synchronously; the DataTransfer is emptied after the event.
    const entries = Array.from(dt.items ?? [])
      .map((it) => (typeof it.webkitGetAsEntry === 'function' ? it.webkitGetAsEntry() : null))
      .filter((en): en is FileSystemEntry => en !== null)
    if (entries.length === 0) {
      deliver(Array.from(dt.files ?? []))
      return
    }
    const out: PathedFile[] = []
    void (async () => {
      try {
        for (const en of entries) await walkEntry(en, out)
      } catch {
        // Unreadable entries are dropped; whatever was read is still delivered.
      }
      deliver(out)
    })()
  }

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
        if (e.dataTransfer) onDropItems(e.dataTransfer)
      }}
      className={`rounded-card border-2 border-dashed p-5 transition-colors duration-150 ${
        dragging ? 'border-brand bg-brand-subtle' : 'border-hairline bg-canvas'
      } ${disabled ? 'opacity-60' : ''}`}
    >
      <label htmlFor={inputId} className="block text-base font-medium text-ink">
        {label}
      </label>
      <p id={helpId} className="mt-1 text-sm text-ink-2">
        Drag files or a whole folder here, or choose them below. Folders are supported and keep their sub-folder names. {help}.
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
          deliver(Array.from(e.target.files ?? []))
          // Allow choosing the same files again after a clear.
          e.target.value = ''
        }}
        className="mt-3 block text-sm text-ink file:mr-3 file:cursor-pointer file:rounded-pill file:border file:border-brand file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium file:text-brand hover:file:bg-brand-subtle"
      />
      <label htmlFor={folderId} className="mt-3 block text-sm font-medium text-ink">
        Choose a folder
      </label>
      <input
        id={folderId}
        data-testid="tender-folder-input"
        type="file"
        {...({ webkitdirectory: '' } as Record<string, string>)}
        disabled={disabled}
        onChange={(e) => {
          deliver(
            Array.from(e.target.files ?? []).map((f) => withPath(f, (f as File & { webkitRelativePath?: string }).webkitRelativePath)),
          )
          e.target.value = ''
        }}
        className="mt-1 block text-sm text-ink file:mr-3 file:cursor-pointer file:rounded-pill file:border file:border-brand file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium file:text-brand hover:file:bg-brand-subtle"
      />
      {skipped > 0 && (
        <p role="status" className="mt-2 text-sm text-ink-2">
          Skipped {skipped} hidden, system or empty {skipped === 1 ? 'file' : 'files'}.
        </p>
      )}
    </div>
  )
}
