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
  external_ai_override?: boolean | null
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

export interface ProjectMemberAdd {
  user_id: string
  project_role?: string | null
}

export interface ProjectMemberOut {
  user_id: string
  project_role: string | null
}

// Mirrors backend/app/schemas/users.py exactly.
export interface UserOut {
  id: string
  username: string
  email: string | null
  enabled: boolean
  roles: string[]
}

// backend/app/core/enums.py::DrawingStatus
export type DrawingStatus =
  | 'uploaded'
  | 'queued'
  | 'converting'
  | 'needs_conversion'
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
  // DWG conversion: kind === 'dwg' is the original upload; the DXF derived
  // from it (downloadable via ?variant=derived) is what gets measured.
  converted_from_dwg: boolean
  derived_size_bytes: number | null
  derived_sha256: string | null
  converter_version: string | null
  conversion_target: string | null
  converted_at: string | null
  conversion_ms: number | null
  conversion_reason: string | null
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
  annotations_status: string | null
}

export interface DrawingAnnotationOut {
  id: string
  sheet_id: string
  page: number | null
  text: string
  kind: string | null
  value: number | null
  unit: string | null
  material: string | null
  bbox: number[] | null
  source: string | null
  confidence: number | null
}

export interface DrawingAnnotationPage {
  items: DrawingAnnotationOut[]
  total: number
  limit: number
  offset: number
}

export interface DrawingAnnotationSummaryOut {
  sheets: number
  done: number
  queued: number
  unavailable: number
  failed: number
  skipped: number
  unread: number
  annotations: number
}

export interface ReadAnnotationsIn {
  drawing_id: string
  force: boolean
}

export interface ReadAnnotationsOut {
  queued_sheets: number
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
  sheet_name?: string | null
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

// Mirrors backend/app/schemas/procurement.py.
export interface ProcurementPackageCreate {
  name: string
  trade_node_id?: string | null
  due_at?: string | null
  notes?: string | null
}

export interface ProcurementPackageOut {
  id: string
  project_id: string
  trade_node_id: string | null
  name: string
  status: string
  due_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface MatchedVendorOut {
  vendor_id: string
  legal_name: string
  primary_email: string | null
  emirate: string | null
  country: string | null
  eligible: boolean
  ineligible_reason: string | null
  service_regions: string[]
}

export interface RfqCreateRequest {
  vendor_ids: string[]
  due_at?: string | null
  override_reason?: string | null
}

export interface RfqOut {
  id: string
  package_id: string
  project_id: string
  vendor_id: string
  vendor_contact_id: string | null
  rfq_ref: string | null
  status: string
  due_at: string | null
  is_override: boolean
  override_reason: string | null
  message_id: string | null
  dispatch_attempts: number
  dispatch_error: string | null
  queued_at: string | null
  sent_at: string | null
  created_at: string
}

// Mirrors backend/app/schemas/quotation_ingestion.py.
export interface InboundEmailOut {
  id: string
  tenant_id: string | null
  rfq_id: string | null
  from_address: string
  from_domain: string
  to_address: string
  subject: string | null
  received_at: string
  match_status: string
  needs_review: boolean
  review_reasons: string[]
  spf_result: string
  dkim_result: string
  dmarc_result: string
  raw_object_key: string
  raw_sha256: string
  review_status: string
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
}

export interface QuotationAttachmentOut {
  id: string
  inbound_email_id: string
  quotation_id: string | null
  is_primary: boolean
  filename: string
  content_type_declared: string | null
  content_type_sniffed: string | null
  size_bytes: number
  safety_status: string
  rejection_reason: string | null
  processed_at: string | null
}

export interface QuotationOut {
  id: string
  rfq_id: string
  vendor_id: string
  package_id: string
  project_id: string
  extraction_method: string
  version_no: number
  is_current: boolean
  currency: string | null
  vat_inclusive: boolean | null
  submitted_at: string
  is_late: boolean
  status: string
  stated_total: number | null
  total_mismatch: boolean
  fx_rate_to_base: number | null
  fx_rate_date: string | null
  created_at: string
}

export interface QuotationLineItemOut {
  id: string
  quotation_id: string
  boq_line_item_id: string | null
  vendor_item_text: string | null
  vendor_description_text: string | null
  unit_price: number | null
  quantity: number | null
  extended_price_stated: number | null
  extended_price_computed: number | null
  arithmetic_mismatch: boolean
  quantity_mismatch: boolean
  vendor_uom: string | null
  uom_mismatch: boolean
  confidence: number
  source: string
  match_method: string | null
  remarks_text: string | null
  status: string
  accepted_by: string | null
  accepted_at: string | null
}

export interface QuotationExclusionFlagOut {
  id: string
  quotation_id: string
  line_item_id: string | null
  flag_text: string
  source_quote_text: string
  source_location: string | null
  citation_verified: boolean
  confidence: number
  status: string
  reviewed_by: string | null
  reviewed_at: string | null
}

export interface BidLevelingCellOut {
  quotation_id: string
  vendor_id: string
  unit_price: number
  currency: string
  vat_inclusive: boolean
  confidence: number
  arithmetic_mismatch: boolean
  quantity_mismatch: boolean
  normalized_unit_price: number | null
  uom_mismatch: boolean
}

export interface BidLevelingRowOut {
  boq_line_item_id: string
  cells: BidLevelingCellOut[]
}

export interface QuotationTotalOut {
  quotation_id: string
  vendor_id: string
  stated_total: number | null
  total_mismatch: boolean
}

export interface QuotationFxRateSet {
  fx_rate_to_base: number
  fx_rate_date: string
}

export interface ResolveInboundTenantRequest {
  tenant_id: string
  note: string
}

export interface AttachInboundEmailRequest {
  rfq_id: string
  reason: string
}

// Mirrors backend/app/schemas/settlement.py.
export interface SimulateLineOverride {
  plant_pct?: number | null
  overhead_pct?: number | null
  volatility_pct?: number | null
  markup_pct?: number | null
}

export interface SimulateRequest {
  default_plant_pct?: number | null
  default_overhead_pct?: number | null
  default_volatility_pct?: number | null
  default_markup_pct?: number | null
  trade_overrides?: Record<string, SimulateLineOverride>
  line_overrides?: Record<string, SimulateLineOverride>
}

export interface SimulateLineResult {
  boq_line_item_id: string
  resolved: boolean
  quantity: number
  direct_unit_cost: number | null
  plant_pct: number
  overhead_pct: number
  volatility_pct: number
  markup_pct: number
  base: number
  plant: number
  overhead: number
  volatility: number
  markup: number
  model_sell: number
  unit_sell_rate: number | null
  line_amount: number | null
}

export interface SimulateResult {
  lines: SimulateLineResult[]
  unresolved_line_ids: string[]
  direct_cost_total: number
  plant_total: number
  overhead_total: number
  volatility_total: number
  markup_total: number
  exact_model_total: number
  tender_total: number
  rounding_difference: number
  margin_on_sell_pct: number | null
  required_role: string | null
}

export interface ScenarioCreate {
  label: string
  inputs: SimulateRequest
}

export interface BidSettlementScenarioOut {
  id: string
  label: string
  inputs: SimulateRequest
  result: SimulateResult
  created_by: string | null
  created_at: string
}

export interface TradeOverrideUpdate {
  plant_pct?: number | null
  overhead_pct?: number | null
  volatility_pct?: number | null
  markup_pct?: number | null
}

export interface LineCostUpdate {
  cost_source?: 'quotation_line' | 'cost_library_rate' | 'manual' | null
  source_quotation_line_item_id?: string | null
  cost_item_id?: string | null
  valid_on?: string | null
  manual_unit_cost?: number | null
  manual_currency?: string | null
  source_note?: string | null
  plant_pct_override?: number | null
  overhead_pct_override?: number | null
  volatility_pct_override?: number | null
  markup_pct_override?: number | null
  line_note?: string | null
}

export interface FxRateSet {
  fx_rate: number
  fx_rate_date: string
}

export interface BidSettlementTradeOverrideOut {
  id: string
  trade_node_id: string
  plant_pct: number | null
  overhead_pct: number | null
  volatility_pct: number | null
  markup_pct: number | null
}

export interface BidSettlementLineItemOut {
  id: string
  boq_line_item_id: string
  quantity: number
  quantity_at_build: number
  direct_unit_cost: number | null
  source_currency: string
  cost_source: string
  source_quotation_line_item_id: string | null
  source_cost_item_rate_id: string | null
  source_rate_as_of_date: string | null
  source_set_by: string | null
  source_set_at: string | null
  source_note: string | null
  fx_rate: number | null
  fx_rate_date: string | null
  plant_pct_override: number | null
  overhead_pct_override: number | null
  volatility_pct_override: number | null
  markup_pct_override: number | null
  unit_sell_rate: number | null
  line_amount: number | null
  line_note: string | null
}

export interface BidSettlementOut {
  id: string
  project_id: string
  version_no: number
  is_current: boolean
  status: string
  currency: string
  default_plant_pct: number
  default_overhead_pct: number
  default_volatility_pct: number
  default_markup_pct: number
  direct_cost_total: number | null
  plant_total: number | null
  overhead_total: number | null
  volatility_total: number | null
  markup_total: number | null
  tender_total: number | null
  rounding_difference: number | null
  margin_on_sell_pct: number | null
  approval_request_id: string | null
  quantities_refreshed_at: string | null
  submitted_at: string | null
  submitted_by: string | null
  decided_at: string | null
  decided_by: string | null
  outcome: 'won' | 'lost' | null
  outcome_our_price: number | null
  outcome_winning_price: number | null
  outcome_competitor_names: string[]
  outcome_competitor_vendor_ids: string[]
  outcome_reason_codes: string[]
  outcome_recorded_by: string | null
  outcome_recorded_at: string | null
  outcome_note: string | null
  notes: string | null
  lines: BidSettlementLineItemOut[]
  trade_overrides: BidSettlementTradeOverrideOut[]
}

export interface SettlementDefaultsUpdate {
  currency?: string | null
  default_plant_pct?: number | null
  default_overhead_pct?: number | null
  default_volatility_pct?: number | null
  default_markup_pct?: number | null
}

export interface OutcomeRequest {
  outcome: 'won' | 'lost'
  our_price?: number | null
  winning_price?: number | null
  competitor_names?: string[]
  competitor_vendor_ids?: string[]
  reason_codes?: string[]
  note?: string | null
}

export interface SettlementReasonCodeOut {
  id: string
  code: string
  label: string
  is_active: boolean
}

export interface ExportRequest {
  include_vat?: boolean
  vat_pct?: number
}

export interface OriginalExportRequest {
  accept_loss?: boolean
}

export interface FidelityReportOut {
  ok: boolean
  lost_features: string[]
  unexpected_cell_changes: string[]
}

export interface ApprovalDecision {
  approve: boolean
  note?: string | null
}

// Mirrors backend/app/schemas/taxonomy.py.
export interface TradeNodeCreate {
  parent_id?: string | null
  code: string
  name: string
  sort_order?: number
  attributes?: Record<string, unknown> | null
}

export interface TradeNodeUpdate {
  name?: string | null
  sort_order?: number | null
  is_active?: boolean | null
  attributes?: Record<string, unknown> | null
}

export interface TradeNodeOut {
  id: string
  parent_id: string | null
  code: string
  name: string
  level: number
  path: string
  sort_order: number
  is_active: boolean
  attributes: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// Mirrors backend/app/schemas/boq.py's tolerance types.
export interface BoqToleranceSet {
  trade_node_id?: string | null
  tolerance_pct: number
}

export interface BoqToleranceOut {
  id: string
  project_id: string
  trade_node_id: string | null
  tolerance_pct: number
  created_at: string
  updated_at: string
}

// Mirrors backend/app/schemas/drawings.py's layer-trade-mapping types.
export interface DrawingLayerTradeMappingIn {
  layer_pattern: string
  trade_node_id: string
}

export interface DrawingLayerTradeMappingOut {
  id: string
  project_id: string
  layer_pattern: string
  trade_node_id: string
}

// Mirrors backend/app/schemas/vendors.py exactly (expanded from the
// admin vendor-regions picker's original 4-field subset for Phase 3's
// vendor master page -- existing callers only used the fields kept here,
// so this is purely additive).
export interface VendorOut {
  id: string
  legal_name: string
  trading_name: string | null
  trade_license_no: string | null
  license_authority: string | null
  trn_vat_no: string | null
  country: string | null
  emirate: string | null
  address_line: string | null
  primary_email: string | null
  primary_phone: string | null
  website_domain: string | null
  status: string
  notes: string | null
  created_at: string
  updated_at: string
}

export interface VendorCreate {
  legal_name: string
  trading_name?: string | null
  trade_license_no?: string | null
  license_authority?: string | null
  trn_vat_no?: string | null
  country?: string | null
  emirate?: string | null
  address_line?: string | null
  primary_email?: string | null
  primary_phone?: string | null
  website_domain?: string | null
  notes?: string | null
}

export interface DuplicateCandidateOut {
  id: string
  vendor_a_id: string
  vendor_b_id: string
  score: number
  signals: Record<string, number> | null
  status: string
  detected_at: string
}

export interface DuplicateCandidatePreview {
  existing_vendor_id: string
  existing_vendor_name: string
  score: number
  signals: Record<string, number>
}

export interface DuplicateCheckResult {
  candidates: DuplicateCandidatePreview[]
  highest_score: number
}

export interface DuplicateResolveRequest {
  resolution: 'confirmed_duplicate' | 'not_duplicate' | 'merged'
  resolution_note?: string | null
}

// Mirrors backend/app/schemas/prequal.py exactly.
export interface AuthorityOut {
  id: string
  code: string
  name: string
  jurisdiction: string | null
}

export interface CertificateTypeOut {
  id: string
  authority_id: string
  code: string
  name: string
  validity_months: number | null
  is_mandatory: boolean
  warn_days_before: number
}

export interface VendorCertificateCreate {
  vendor_id: string
  certificate_type_id: string
  certificate_no?: string | null
  issue_date?: string | null
  expiry_date?: string | null
  document_object_key?: string | null
  document_sha256?: string | null
}

export interface VendorCertificateOut {
  id: string
  vendor_id: string
  certificate_type_id: string
  certificate_no: string | null
  issue_date: string | null
  expiry_date: string | null
  status: string
  verified_by: string | null
  verified_at: string | null
}

// Mirrors backend/app/schemas/prequal.py's ExpiringVendorCertificateOut
// exactly (Phase 3 gap-fill, docs/ui-qa-brief.md: home dashboard).
export interface ExpiringVendorCertificateOut {
  id: string
  vendor_id: string
  vendor_name: string
  certificate_type_id: string
  expiry_date: string
  status: string
}

export interface PrequalificationDecision {
  status: string
  grade?: string | null
  max_award_value?: number | null
  scope_trade_node_id?: string | null
  effective_from: string
  decision_note?: string | null
}

export interface VendorPrequalificationOut {
  id: string
  vendor_id: string
  status: string
  grade: string | null
  max_award_value: number | null
  scope_trade_node_id: string | null
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

// Mirrors backend/app/schemas/costlib.py exactly. unit_cost/amount/
// total_rate/confidence are bare `number` here because the backend itself
// uses plain float, not Decimal/JsonDecimal, for cost-library money fields
// end to end (a pre-existing, different issue from the JsonDecimal-string
// bug fixed elsewhere -- flagged in docs/ui-qa/log.md Phase 3 for the main
// session, not something this UI can fix on its own).
export interface CostItemOut {
  id: string
  code: string
  description: string
  uom: string
  trade_node_id: string | null
  item_type: string
  is_active: boolean
}

export interface CostItemCreate {
  code: string
  description: string
  long_description?: string | null
  uom: string
  trade_node_id?: string | null
  item_type?: string
  attributes?: Record<string, unknown> | null
}

export interface CostRateComponentIn {
  component_type: string
  description: string
  resource_code?: string | null
  quantity_per_uom?: number
  unit_cost: number
  waste_factor?: number
  productivity?: number | null
  sort_order?: number
}

export interface CostRateComponentOut {
  id: string
  component_type: string
  description: string
  resource_code: string | null
  quantity_per_uom: number
  unit_cost: number
  waste_factor: number
  amount: number
  sort_order: number
}

export interface RecordRateRequest {
  scope_key?: string
  currency?: string
  valid_from: string
  valid_to?: string | null
  source?: string
  source_ref?: string | null
  confidence?: number | null
  components: CostRateComponentIn[]
}

export interface CostItemRateOut {
  id: string
  cost_item_id: string
  scope_key: string
  currency: string
  total_rate: number
  source: string
  source_ref: string | null
  confidence: number | null
  components: CostRateComponentOut[]
}

// Mirrors backend/app/schemas/module_e.py exactly.
export interface ContractOut {
  id: string
  project_id: string
  settlement_id: string
  contract_ref: string | null
  status: string
  awarded_at: string | null
  created_at: string
}

export interface BoqRevisionOut {
  id: string
  project_id: string
  revision_no: number
  parent_revision_id: string | null
  import_batch_id: string | null
  reason: string | null
  created_at: string
}

export interface ContractRevisionOut {
  id: string
  project_id: string
  contract_id: string
  revision_no: number
  parent_revision_id: string | null
  reason: string | null
  created_at: string
}

export interface ContractVariationOut {
  id: string
  project_id: string
  contract_id: string
  revision_id: string
  variation_ref: string | null
  description: string
  delta_amount: number | null
  status: string
  created_at: string
}

export interface ExclusionRegisterEntryOut {
  id: string
  project_id: string
  contract_id: string | null
  source_exclusion_flag_id: string | null
  description: string
  status: string
  resolution_note: string | null
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
}

export interface OutturnCostObservationOut {
  id: string
  project_id: string
  contract_id: string
  boq_line_item_id: string | null
  cost_item_id: string | null
  observed_unit_cost: number
  observed_quantity: number | null
  currency: string
  observed_at: string
  source_note: string | null
  written_back_rate_id: string | null
  created_at: string
}

// Mirrors backend/app/schemas/approvals.py.
export interface ApprovalPolicyTierIn {
  seq: number
  min_amount?: number
  max_amount?: number | null
  max_margin_pct?: number | null
  required_role: string
  quorum?: number
  sla_hours?: number | null
  requires_mfa?: boolean
}

export interface ApprovalPolicyTierOut {
  id: string
  policy_id: string
  seq: number
  min_amount: number
  max_amount: number | null
  max_margin_pct: number | null
  required_role: string
  quorum: number
  sla_hours: number | null
  requires_mfa: boolean
}

export interface ApprovalPolicyCreate {
  entity_type: string
  name: string
  mode?: string
  tiers: ApprovalPolicyTierIn[]
}

export interface ApprovalPolicyOut {
  id: string
  entity_type: string
  name: string
  version: number
  mode: string
  is_active: boolean
  tiers: ApprovalPolicyTierOut[]
}

// Mirrors backend/app/schemas/approvals.py's ApprovalStepOut/ApprovalRequestOut
// exactly (Phase 3 gap-fill, docs/ui-qa-brief.md: home dashboard's
// "approvals waiting for me" tile).
export interface ApprovalStepOut {
  id: string
  seq: number
  required_role: string
  status: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
}

export interface ApprovalRequestOut {
  id: string
  project_id: string | null
  entity_type: string
  entity_id: string
  amount: number
  currency: string
  status: string
  current_seq: number
  requested_by: string
  requested_at: string
  completed_at: string | null
  steps: ApprovalStepOut[]
  project_code: string | null
  project_name: string | null
  requested_by_name: string | null
  waiting_role: string | null
  settlement_version_no: number | null
  margin_on_sell_pct: number | null
  view_state: 'actionable' | 'awaiting_other' | 'decided' | 'other' | null
  payload_snapshot: Record<string, unknown> | null
}

export interface ApprovalInboxOut {
  pending: ApprovalRequestOut[]
  recent: ApprovalRequestOut[]
}

export interface ApprovalPolicySetActive {
  is_active: boolean
}

export interface ReasonCodeCreate {
  code: string
  label: string
}

export interface ReasonCodeUpdate {
  label?: string | null
  is_active?: boolean | null
}

// Mirrors backend/app/schemas/audit.py.
export interface AuditEventOut {
  id: number
  occurred_at: string
  actor_sub: string | null
  actor_roles: string[]
  action: string
  entity_type: string
  entity_id: string | null
  project_id: string | null
  ip_address: string | null
  seq: number
  event_hash: string
}

export interface ChainVerifyResult {
  tenant_id: string
  date_from: string
  date_to: string
  ok: boolean
  detail?: string | null
}

// --- external AI governance ---

export interface AiStatusOut {
  provider: string
  external: boolean
  configured: boolean
  external_ai_allowed: boolean
  available: boolean
  message: string | null
}

export interface AiSettingsOut {
  external_ai_allowed: boolean
  provider: string
  external: boolean
  configured: boolean
}

export type AiCallStatus = 'ok' | 'cached' | 'error' | 'blocked'

export interface AiUsageRow {
  task: string
  provider: string
  model: string
  calls: number
  cached: number
  errors: number
  blocked: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
}

export interface AiRecentCall {
  id: string
  created_at: string
  task: string
  provider: string
  model: string
  project_id: string | null
  entity_type: string | null
  entity_id: string | null
  status: AiCallStatus
  tokens_in: number
  tokens_out: number
  cost_usd: number
  latency_ms: number
  error: string | null
  created_by: string | null
}

export interface AiUsageOut {
  month_to_date_usd: number
  monthly_budget_usd: number | null
  project_budget_usd: number | null
  rows: AiUsageRow[]
  recent: AiRecentCall[]
}

export interface ProjectAiOverrideOut {
  project_id: string
  external_ai_override: boolean | null
}

// --- PDF BOQ extraction (features/boq/pdf) ---

export type BoqPdfExtractionStatus = 'queued' | 'running' | 'ready' | 'failed' | 'committed'

export type BoqPdfPageStatus = 'table' | 'ai' | 'skipped_collection' | 'empty' | 'needs_ai' | 'ai_unavailable'

export interface BoqPdfExtractionOut {
  id: string
  project_id: string
  document_id: string | null
  source_filename: string
  status: BoqPdfExtractionStatus
  use_ai: boolean
  pages_total: number | null
  pages_done: number | null
  warnings: string[]
  error: string | null
  batch_id: string | null
  committed_at: string | null
  created_at: string
}

export interface BoqPdfPageInfo {
  page: number
  status: BoqPdfPageStatus
  note?: string | null
  rows?: number | null
  quality?: number | null
}

export interface BoqPdfRow {
  row_id: string
  page: number
  item_no: string | null
  description: string | null
  uom: string | null
  quantity: number | null
  bbox: number[] | null
  page_size: number[] | null
  source: 'table' | 'ai' | 'manual'
  confidence: number | null
  edited: boolean
  ai_read: boolean
  errors: string[]
}

export interface BoqPdfExtractionDetail extends BoqPdfExtractionOut {
  pages: BoqPdfPageInfo[]
  rows: BoqPdfRow[]
  valid_count: number
  error_count: number
  ai_row_count: number
  original_workbook_export_available: boolean
}

export interface BoqPdfRowIn {
  row_id?: string
  item_no: string
  description: string
  uom: string
  quantity: number | null
  page: number
}

export interface BoqPdfCommitOut {
  created_count: number
  batch_id: string
  created_item_ids: string[]
}

export interface BoqPdfFileUrlOut {
  url: string
  filename: string
}

// --- Drawing vs BOQ verification ---
export type VerificationRunStatus = 'queued' | 'running' | 'ready' | 'failed'
export type VerificationPhase = 'loading' | 'interpreting' | 'ranking' | 'computing'
export type VerificationClass =
  | 'match'
  | 'variance'
  | 'missing_in_drawings'
  | 'not_verifiable'
  | 'missing_in_boq'

export type VerificationCounts = Record<VerificationClass, number>

export interface VerificationTradeSummary {
  trade: string
  lines: number
  match: number
  variance: number
  missing_in_drawings: number
  not_verifiable: number
  abs_variance_pct_sum: number
}

export interface VerificationTopRisk {
  /** null for "missing in BOQ": a drawing item has no BOQ line */
  line_id: string | null
  class: VerificationClass
  delta_pct: number | null
  note: string
}

export interface VerificationRunOut {
  id: string
  project_id: string
  status: VerificationRunStatus
  use_ai: boolean
  phase: VerificationPhase | null
  progress_done: number
  progress_total: number
  counts: VerificationCounts
  summary: { verifiable: number; by_trade: VerificationTradeSummary[]; top_risks: VerificationTopRisk[] }
  warnings: string[]
  error: string | null
  ai_calls: number
  ai_cost_usd: number
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface VerificationEvidenceOut {
  ref: string
  kind: 'measurement' | 'annotation'
  value: number | null
  unit: string | null
  label: string | null
  drawing_id: string
  sheet_id: string | null
  page: number
  bbox: number[] | null
  layer: string | null
  confidence: number | null
  material: string | null
}

export interface VerificationCandidateOut {
  ref: string
  score: number
  reason: string
  source: 'ai' | 'rules'
  selected: boolean
}

export interface VerificationInterpretationOut {
  work_type: string | null
  material: string | null
  size_mm: number | null
  unit: string | null
  trade: string | null
  source: string | null
  keywords: string[]
}

export interface VerificationLineOut {
  id: string
  run_id: string
  boq_line_item_id: string | null
  item_no: string | null
  description: string
  trade_name: string | null
  vclass: VerificationClass
  method: 'measured' | 'annotated' | 'none'
  mapped_by: 'ai' | 'rules' | 'user' | 'none'
  boq_quantity: number | null
  boq_uom: string | null
  drawing_quantity: number | null
  delta: number | null
  delta_pct: number | null
  confidence: number
  note: string | null
  flags: string[]
  interpretation: VerificationInterpretationOut | null
  evidence: VerificationEvidenceOut[]
  candidates: VerificationCandidateOut[]
}

export interface VerificationLinesPage {
  items: VerificationLineOut[]
  total: number
  limit: number
  offset: number
}

export type VerificationMappingAction = 'accept' | 'reject' | 'include' | 'clear'

export interface VerificationMappingRequest {
  action: VerificationMappingAction
  evidence_ref: string
  note?: string
}

export interface VerificationMappingResult {
  line: VerificationLineOut
  run: VerificationRunOut
}

export interface AnnotationSummaryOut {
  sheets: number
  done: number
  queued: number
  unavailable: number
  failed: number
  skipped: number
  unread: number
  annotations: number
}

// --- AI pricing assistant (settlement draft) ---
export type SettlementAiRunKind = 'costs' | 'markup'
export type SettlementAiRunStatus = 'queued' | 'running' | 'ready' | 'failed'

export interface SettlementAiCostCounts {
  lines: number
  with_source: number
  no_source: number
  ai_chosen: number
  rules_chosen: number
  blocked: number
  bulk_acceptable: number
}

export interface MarkupAdviceOption {
  label: 'competitive' | 'balanced' | 'protective'
  markup_pct: number
  overhead_pct: number
  volatility_pct: number
  rationale: string
  tender_total: string
  margin_on_sell_pct: string | null
  required_role: string | null
  unresolved_lines: number
}

export interface MarkupAdviceTrade {
  trade: string
  markup_low: number
  markup_high: number
  volatility_low: number | null
  volatility_high: number | null
  rationale: string
}

export interface MarkupAdviceHistoryRow {
  margin_bucket: string
  bids: number
  won: number
  win_rate_pct: number | null
  avg_price_gap_when_lost_pct: number | null
}

export interface MarkupAdviceResult {
  options: MarkupAdviceOption[]
  per_trade: MarkupAdviceTrade[]
  overall: string | null
  history: MarkupAdviceHistoryRow[]
  current: { tender_total: string; margin_on_sell_pct: string | null; required_role: string | null }
  context?: Record<string, unknown>
}

export interface SettlementAiRun {
  id: string
  settlement_id: string
  kind: SettlementAiRunKind
  status: SettlementAiRunStatus
  use_ai: boolean
  progress_done: number
  progress_total: number
  counts: Partial<SettlementAiCostCounts> | null
  result: MarkupAdviceResult | null
  warnings: string[]
  error: string | null
  ai_calls: number
  ai_cost_usd: number
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export type CostCandidateType = 'quote' | 'library' | 'historical'

export interface CostCandidate {
  ref: string
  type: CostCandidateType
  label: string
  rate: number
  currency: string
  uom: string
  vendor: string | null
  as_of: string | null
  samples: number
  match_score: number
  score: number
  reason: string
  selected: boolean
  flags: string[]
  detail: {
    age_months?: number
    deviation_pct?: number
    components?: unknown
    open_exclusions?: unknown
    min?: number
    max?: number
    [key: string]: unknown
  }
}

export type CostProposalStatus = 'proposed' | 'accepted' | 'overridden' | 'rejected'

export interface CostProposal {
  id: string
  run_id: string
  settlement_id: string
  settlement_line_id: string
  boq_line_item_id: string
  item_no: string | null
  description: string
  uom: string | null
  quantity: number
  status: CostProposalStatus
  source: 'ai' | 'rules' | 'none'
  chosen: CostCandidate | null
  candidates: CostCandidate[]
  rationale: string | null
  flags: string[]
  blocked: boolean
  bulk_acceptable: boolean
  no_source: boolean
  confidence: number
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  created_at: string
}

export interface CostProposalPage {
  items: CostProposal[]
  total: number
  limit: number
  offset: number
}

export interface CostProposalDecision {
  action: 'accept' | 'choose' | 'manual' | 'reject'
  candidate_ref?: string
  manual_unit_cost?: number
  manual_currency?: string
  note?: string
}

export interface BulkAcceptResult {
  accepted: number
  skipped: number
}
