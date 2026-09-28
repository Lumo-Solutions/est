import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import type { ColDef } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo } from 'react'
import type { BoqLineItemOut } from '../../types/api'

ModuleRegistry.registerModules([AllCommunityModule])

// docs/ui-design-system.md section 4.4 -- Theming API params only (a
// CSS-variable-level change AG Grid already optimizes for), no row/column
// virtualization or other perf setting touched. The 5,000-row benchmark
// (frontend/e2e/boq-reconciliation.spec.ts) is re-run after this change,
// not assumed safe.
const installtecGridTheme = themeQuartz.withParams({
  accentColor: '#1D4ED8',
  headerBackgroundColor: '#F8FAFC',
  headerTextColor: '#475569',
  oddRowBackgroundColor: '#FFFFFF',
  rowHoverColor: '#F8FAFC',
  fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
  fontSize: 13,
})

const COLUMN_DEFS: ColDef<BoqLineItemOut>[] = [
  { field: 'item_no', headerName: 'Item No', width: 110, pinned: 'left' },
  { field: 'description', headerName: 'Description', flex: 1, minWidth: 200 },
  { field: 'uom', headerName: 'UoM', width: 80 },
  { field: 'boq_quantity', headerName: 'BOQ Qty', width: 110, valueFormatter: (p) => p.value?.toFixed(2) ?? '--' },
  { field: 'variance', headerName: 'Variance', width: 110, valueFormatter: (p) => p.value?.toFixed(2) ?? '--' },
  {
    field: 'variance_pct',
    headerName: 'Variance %',
    width: 110,
    valueFormatter: (p) => (p.value != null ? `${p.value.toFixed(1)}%` : '--'),
  },
  { field: 'discrepancy_class', headerName: 'Discrepancy', width: 140 },
  { field: 'reconciliation_note', headerName: 'Note', flex: 1, minWidth: 160 },
]

interface Props {
  rows: BoqLineItemOut[]
  onRowClick: (item: BoqLineItemOut) => void
}

export function BoqReconciliationGrid({ rows, onRowClick }: Props) {
  const columnDefs = useMemo(() => COLUMN_DEFS, [])

  return (
    <div style={{ height: '100%', width: '100%' }}>
      <AgGridReact<BoqLineItemOut>
        theme={installtecGridTheme}
        rowData={rows}
        columnDefs={columnDefs}
        getRowId={(p) => p.data.id}
        onRowClicked={(e) => e.data && onRowClick(e.data)}
      />
    </div>
  )
}
