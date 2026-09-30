import { useId, useState } from 'react'
import { Card } from '../../components/Card'

// A collapsible card section. `lazy` mounts the body only once opened (the registers fetch on mount);
// otherwise the body stays mounted while closed so typed-in state survives a collapse.
export function Disclosure({
  title,
  hint,
  defaultOpen = false,
  lazy = false,
  children,
}: {
  title: string
  hint?: string
  defaultOpen?: boolean
  lazy?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  return (
    <Card className="mt-6">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline justify-between gap-4 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        <span className="text-section font-semibold text-ink-title">{title}</span>
        <span className="shrink-0 text-sm text-ink-2">
          {hint ? `${hint} ` : ''}
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      <div id={bodyId} hidden={!open}>
        {(open || !lazy) && <div className="mt-3">{children}</div>}
      </div>
    </Card>
  )
}
