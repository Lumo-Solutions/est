import { Modal } from './Modal'

// A yes/no sibling to TextPromptModal.tsx for actions that need a
// confirmation step but no free-text input -- e.g. TaxonomyAdmin.tsx's
// "move this node under a different parent" (Phase 3 gap-fill,
// docs/ui-qa-brief.md), which would otherwise reach for window.confirm.
export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  message?: string
  confirmLabel?: string
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      {message && <p className="mt-1 text-sm text-slate-500">{message}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
