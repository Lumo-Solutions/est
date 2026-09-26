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

// Mirrors backend/app/schemas/typology.py.
export type TypologyClusterStatus = 'proposed' | 'confirmed' | 'rejected'

export interface TypologyClusterOut {
  id: string
  project_id: string
  status: TypologyClusterStatus
  master_instance_id: string | null
  detection_method: string
  detection_key: string
  tolerance_pct: number
  confirmed_by: string | null
  confirmed_at: string | null
  created_at: string
}

export interface TypologyClusterInstanceOut {
  id: string
  cluster_id: string
  sheet_id: string | null
  bbox_min_x: number | null
  bbox_min_y: number | null
  bbox_max_x: number | null
  bbox_max_y: number | null
  group_label: string
  instance_count: number
  source_handles: string[]
}

export interface TypologyVariantDeltaOut {
  id: string
  cluster_id: string
  group_label: string
  description: string
  boq_line_item_id: string | null
  quantity_delta: number | null
  unit: string | null
}

export interface ConfirmClusterGroupIn {
  group_label: string
  handles: string[]
}

export interface ConfirmClusterDeltaIn {
  group_label: string
  description: string
  boq_line_item_id?: string | null
  quantity_delta?: number | null
  unit?: string | null
}

export interface ConfirmClusterRequest {
  groups: ConfirmClusterGroupIn[]
  master_group_label: string
  deltas: ConfirmClusterDeltaIn[]
}

export interface TypologyRollupDeltaOut {
  group_label: string
  quantity_delta: number
  instance_count: number
  contribution: number
}

export interface TypologyRollupItemOut {
  boq_line_item_id: string
  item_no: string
  master_quantity: number
  total_instance_count: number
  total: number
  deltas: TypologyRollupDeltaOut[]
}

export interface TypologyRollupOut {
  cluster_id: string
  total_instance_count: number
  items: TypologyRollupItemOut[]
  note: string | null
}

// Mirrors backend/app/schemas/boq.py.
export interface BoqLineItemOut {
  id: string
  project_id: string
  parent_id: string | null
  item_no: string
  description: string
  uom: string | null
  boq_quantity: number | null
  trade_node_id: string | null
  level: number
  path: string
  sort_order: number
  variance: number | null
  variance_pct: number | null
  discrepancy_class: string | null
  reconciliation_note: string | null
  reconciled_at: string | null
  created_at: string
}

export interface LinkedMeasurementOut {
  id: string
  drawing_id: string
  sheet_id: string
  capability: string
  kind: string
  value: number
  unit: string
  confidence: number
  trade_node_id: string | null
  effective_value: number
}

export interface BoqImportColumnMappingIn {
  item_no_column: string
  description_column: string
  uom_column?: string | null
  quantity_column?: string | null
  parent_column?: string | null
  rate_column?: string | null
  amount_column?: string | null
  header_row?: number
}

export interface BoqImportRowOut {
  row_number: number
  item_no: string | null
  description: string | null
  uom: string | null
  boq_quantity: number | null
  parent_item_no: string | null
  errors: string[]
}

export interface BoqImportPreviewOut {
  rows: BoqImportRowOut[]
  valid_count: number
  error_count: number
}

export interface BoqImportCommitOut {
  created_item_ids: string[]
  created_count: number
}

// Mirrors backend/app/schemas/semantic_matching.py.
export interface SuggestionOut {
  target_id: string
  fuzzy_score: number
  semantic_score: number | null
  combined_score: number
  rag_adjustment: number
  final_score: number
}

export type FeedbackOutcome = 'accepted' | 'rejected'

export interface FeedbackCreate {
  match_type: 'boq_measurement' | 'quote_boq'
  query_embedding_source_id: string
  target_id: string
  outcome: FeedbackOutcome
}
