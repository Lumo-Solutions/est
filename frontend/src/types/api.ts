// Mirrors backend/app/schemas/{projects,drawings}.py exactly -- field names
// and nullability kept in lockstep with the Pydantic models they serialize.

export interface ProjectOut {
  id: string
  code: string
  name: string
  client_name: string | null
  status: string
  tender_ref: string | null
  base_currency: string
  emirate: string | null
  area: string | null
  latitude: number | null
  longitude: number | null
  created_at: string
}

export interface ProjectCreate {
  code: string
  name: string
  client_name?: string | null
  tender_ref?: string | null
  base_currency?: string
}

export interface ProjectLocationUpdate {
  emirate?: string | null
  area?: string | null
  latitude?: number | null
  longitude?: number | null
}

// backend/app/core/enums.py::DrawingStatus
export type DrawingStatus =
  | 'uploaded'
  | 'queued'
  | 'indexing'
  | 'extracting'
  | 'embedding'
  | 'ready'
  | 'failed'
  | 'partial'

export interface DrawingOut {
  id: string
  project_id: string
  original_filename: string
  content_type: string | null
  kind: string
  size_bytes: number
  sha256: string
  sheet_count: number | null
  status: DrawingStatus
  error_message: string | null
  created_at: string
}

export interface DrawingSheetOut {
  id: string
  drawing_id: string
  sheet_index: number
  source_name: string | null
  is_raster: boolean
  text_char_count: number | null
  title_block: Record<string, unknown> | null
  drawing_number: string | null
  sheet_title: string | null
  revision: string | null
  issue_date: string | null
  discipline: string | null
  scale_text: string | null
  scale_ratio: number | null
  scale_source: string | null
  scale_confidence: number | null
  scale_disagreement: boolean
  extraction_status: string | null
}

export interface ManualScaleCalibrationIn {
  p1: [number, number]
  p2: [number, number]
  known_length_m: number
}

export interface ExtractionJobOut {
  id: string
  job_type: string
  status: string
  attempt: number
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error: string | null
}

export interface DrawingMeasurementOut {
  id: string
  drawing_id: string
  sheet_id: string
  capability: string
  kind: string
  value: number
  unit: string
  confidence: number
  source_entity_ids: string[]
  extractor_metadata: Record<string, unknown> | null
  created_at: string
  trade_node_id: string | null
  bbox_min_x: number | null
  bbox_min_y: number | null
  bbox_max_x: number | null
  bbox_max_y: number | null
  effective_value: number
}

export interface SheetScaleCalibrationOut {
  id: string
  ratio: number | null
  source: string
  confidence: number
  set_by: string | null
  set_at: string
  note: string | null
}

export interface MeasurementOverrideIn {
  value: number
  unit: string
  note: string
}

export interface MeasurementOverrideOut {
  id: string
  measurement_id: string
  value: number
  unit: string
  note: string
  overridden_by: string | null
  overridden_at: string
  reverted_by: string | null
  reverted_at: string | null
}

export interface EntityGeometry {
  vertices: [number, number][]
  closed: boolean
  bulges: (number | null)[] | null
  center: [number, number] | null
  radius: number | null
  start_angle_deg: number | null
  end_angle_deg: number | null
}

export interface DrawingEntityOut {
  id: string
  sheet_id: string
  source: string
  entity_type: string
  layer: string | null
  block_name: string | null
  text_value: string | null
  bbox_min_x: number | null
  bbox_min_y: number | null
  bbox_max_x: number | null
  bbox_max_y: number | null
  geometry: EntityGeometry | null
  handle: string | null
}
