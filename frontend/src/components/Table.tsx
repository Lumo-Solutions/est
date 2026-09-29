import { createContext, useContext } from 'react'
import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'

// Two densities (docs/figma-implementation-plan.md D2):
//  - comfortable: Figma's 16px / tall rows -- short lists (Projects, Vendors,
//    Cost library, Inbox, Post-award).
//  - dense: today's 14px / py-2 metrics -- BOQ, quote review, bid leveling,
//    settlement, audit. AG Grid is NOT routed through here at all.
export type TableDensity = 'comfortable' | 'dense'

const DensityContext = createContext<TableDensity>('dense')

const CELL_PAD: Record<TableDensity, string> = {
  comfortable: 'px-4 py-4 text-base',
  dense: 'px-3 py-2 text-sm',
}

export function Table({
  density = 'dense',
  className = '',
  children,
  ...rest
}: { density?: TableDensity } & HTMLAttributes<HTMLTableElement>) {
  return (
    <DensityContext.Provider value={density}>
      <table className={`w-full text-left ${className}`} {...rest}>
        {children}
      </table>
    </DensityContext.Provider>
  )
}

export function Th({ className = '', numeric, ...rest }: { numeric?: boolean } & ThHTMLAttributes<HTMLTableCellElement>) {
  const density = useContext(DensityContext)
  return (
    <th
      className={`border-b border-hairline font-medium text-muted ${CELL_PAD[density]} ${numeric ? 'text-right' : ''} ${className}`}
      {...rest}
    />
  )
}

export function Td({ className = '', numeric, ...rest }: { numeric?: boolean } & TdHTMLAttributes<HTMLTableCellElement>) {
  const density = useContext(DensityContext)
  return (
    <td
      className={`border-b border-row-rule text-ink ${CELL_PAD[density]} ${numeric ? 'text-right tabular-nums' : ''} ${className}`}
      {...rest}
    />
  )
}

// A table sits inside a rounded white card; this wrapper gives it the Figma
// table-card look and horizontal scroll at narrow widths instead of
// page-level overflow (layout-widths.spec fails on page-level overflow).
export function TableCard({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return <div className={`overflow-x-auto rounded-card bg-white p-2 ${className}`}>{children}</div>
}
