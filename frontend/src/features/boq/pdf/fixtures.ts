import type { BoqPdfExtractionDetail, BoqPdfRow } from '../../../types/api'

export function makeRow(over: Partial<BoqPdfRow> = {}): BoqPdfRow {
  return {
    row_id: 'r1',
    page: 2,
    item_no: '1.1',
    description: 'Cable tray',
    uom: 'm',
    quantity: 10,
    bbox: [0, 0, 10, 10],
    page_size: [595, 842],
    source: 'table',
    confidence: null,
    edited: false,
    ai_read: false,
    errors: [],
    ...over,
  }
}

export function makeExtraction(over: Partial<BoqPdfExtractionDetail> = {}): BoqPdfExtractionDetail {
  return {
    id: 'x1',
    project_id: 'p1',
    document_id: null,
    source_filename: 'boq.pdf',
    status: 'ready',
    use_ai: true,
    pages_total: 3,
    pages_done: 3,
    warnings: [],
    error: null,
    batch_id: null,
    committed_at: null,
    created_at: '2026-09-01T00:00:00Z',
    pages: [],
    rows: [],
    valid_count: 0,
    error_count: 0,
    ai_row_count: 0,
    original_workbook_export_available: false,
    ...over,
  }
}
