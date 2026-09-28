import { useEffect } from 'react'

// Phase 3 gap-fill (docs/ui-qa-brief.md): the first shared modal/dialog
// component in this codebase -- every existing "confirm/enter text" action
// used a blocking native window.prompt instead (see TextPromptModal.tsx,
// built on this, for the replacement). Deliberately minimal: backdrop
// click and Escape both dismiss, no focus trap (not required for this
// pass's single-input-plus-two-buttons dialogs).
export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-lg bg-white p-4 shadow-lg"
      >
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        {children}
      </div>
    </div>
  )
}
