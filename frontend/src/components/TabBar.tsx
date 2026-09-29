import { useRef } from 'react'

// Figma Transaction/Setting tabs: 16/500, active = brand text + 3px brand
// underline with a 10px top radius. WAI-ARIA tabs pattern: roving tabindex
// and Arrow/Home/End keys, so it stays fully keyboard-operable. Tab *names*
// are the labels passed in -- existing e2e specs locate tabs by role+name,
// so callers must keep their current label text.
export interface TabItem {
  id: string
  label: string
}

export function TabBar({
  tabs,
  value,
  onChange,
  label,
  idPrefix,
}: {
  tabs: TabItem[]
  value: string
  onChange: (id: string) => void
  label: string
  // Panels carry id={`${idPrefix}-panel-${tab.id}`} and
  // aria-labelledby={`${idPrefix}-tab-${tab.id}`}.
  idPrefix: string
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const move = (fromIdx: number, delta: number | 'first' | 'last') => {
    const next =
      delta === 'first' ? 0 : delta === 'last' ? tabs.length - 1 : (fromIdx + delta + tabs.length) % tabs.length
    const t = tabs[next]
    onChange(t.id)
    refs.current[t.id]?.focus()
  }

  return (
    <div role="tablist" aria-label={label} className="flex gap-8 border-b border-hairline">
      {tabs.map((t, i) => {
        const active = t.id === value
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${t.id}`}
            aria-selected={active}
            aria-controls={`${idPrefix}-panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => {
              const delta =
                e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'Home' ? 'first' : e.key === 'End' ? 'last' : null
              if (delta === null) return
              e.preventDefault()
              move(i, delta)
            }}
            className={`-mb-px border-b-[3px] px-2 pb-3 text-base font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
              active ? 'rounded-t-bar border-brand text-brand' : 'border-transparent text-muted hover:text-brand'
            }`}
          >
            {t.label}
          </button>
        )
      })}
    </div>
  )
}
