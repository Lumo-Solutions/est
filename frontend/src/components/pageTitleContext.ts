import { createContext } from 'react'

// AppShell provides the header element the page <h1> is portalled into
// (docs/figma-implementation-plan.md 3.1). null outside the shell (unit
// tests rendering a page standalone) -> PageTitle falls back to inline.
export const PageTitleSlotContext = createContext<HTMLElement | null>(null)
