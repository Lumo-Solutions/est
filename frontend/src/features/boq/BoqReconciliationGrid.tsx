import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import type { ColDef } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo } from 'react'
import type { BoqLineItemOut } from '../../types/api'

ModuleRegistry.registerModules([AllCommunityModule])

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
        theme={themeQuartz}
        rowData={rows}
        columnDefs={columnDefs}
        getRowId={(p) => p.data.id}
        onRowClicked={(e) => e.data && onRowClick(e.data)}
      />
    </div>
  )
}
