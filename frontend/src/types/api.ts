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
