import { useContext } from 'react'
import { createPortal } from 'react-dom'
import { PageTitleSlotContext } from './pageTitleContext'

// Figma puts the 28px page title in the 100px header. Each page still OWNS
// its title (and its single <h1>): this portals the real <h1> into the
// header slot, so heading semantics, axe's page-has-heading-one and every
// e2e getByRole('heading', { name }) keep working unchanged.
export function PageTitle({ children }: { children: React.ReactNode }) {
  const slot = useContext(PageTitleSlotContext)
  const h1 = <h1 className="truncate text-page-title font-semibold text-ink-title">{children}</h1>
  if (!slot) return <div className="px-10 pt-6">{h1}</div>
  return createPortal(h1, slot)
}
