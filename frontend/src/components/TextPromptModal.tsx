import { useState } from 'react'
import { Modal } from './Modal'

// Phase 3 gap-fill (docs/ui-qa-brief.md): every current window.prompt call
// site in this app asks for one required line of text (a reason/note) and
// treats an empty/cancelled result as "do nothing" -- this is that same
// shape as a modal instead of a blocking native dialog. Submit stays
// disabled until the trimmed value is non-empty, matching every existing
// call site's own `if (reason) mutate(...)` guard.
export function TextPromptModal({
  open,
  title,
  message,
  submitLabel = 'Submit',
  onCancel,
  onSubmit,
}: {
  open: boolean
  title: string
  message?: string
  submitLabel?: string
  onCancel: () => void
  onSubmit: (value: string) => void
}) {
  const [value, setValue] = useState('')

  const close = () => {
    setValue('')
    onCancel()
  }

  return (
    <Modal open={open} title={title} onClose={close}>
      {message && <p className="mt-1 text-sm text-slate-500">{message}</p>}
      <textarea
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={3}
        className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      />
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={close}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!value.trim()}
          onClick={() => {
            const submitted = value.trim()
            setValue('')
            onSubmit(submitted)
          }}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {submitLabel}
        </button>
      </div>
    </Modal>
  )
}
