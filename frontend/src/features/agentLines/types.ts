// Shapes of docs/boq-agent/api-contract.md that the settlement page and the document tree use.
// Kept here (not in types/api.ts) so the agent UI stays in one place.

export type AgentCostSource = 'agent_candidate' | 'agent_estimate'

export type AgentEvidence =
  | { kind?: string; file_id: string; path: string; page?: number | null; quote?: string | null }
  | { kind: 'cost_source'; ref: string; label: string; type: string }

export interface QtyCheck {
  boq_quantity: number
  measured: number | null
  unit: string | null
  delta_pct: number | null
  class: string | null
}

export interface AgentProposal {
  id: string
  run_id: string
  boq_line_item_id: string
  kind: 'candidate' | 'estimate'
  candidate_ref: string | null
  rate: number | null
  currency: string | null
  uom: string | null
  as_of: string | null
  method: string | null
  evidence: AgentEvidence[]
  qty_check: QtyCheck | null
  flags: string[]
  confidence: number | null
  rationale: string | null
  status: 'proposed' | 'applied' | 'superseded' | 'rejected_by_user'
  applied_at: string | null
}

export interface AgentLine {
  line_id: string
  boq_line_item_id: string
  cost_source: AgentCostSource
  direct_unit_cost: number | null
  source_currency: string
  agent_proposal_id: string | null
  agent_confirmed_by: string | null
  agent_confirmed_at: string | null
  proposal: AgentProposal | null
}

export interface AgentSummary {
  agent_lines: number
  unconfirmed: number
}

export interface BulkConfirmResult {
  confirmed: number
  skipped: { estimate: number; blocked_or_low_confidence: number }
}

// The slice of the run payloads the document tree needs.
export interface AgentRunRef {
  id: string
}
export interface AgentRunSections {
  sections?: { coverage?: { files_read?: { file_id: string }[] } | null }[]
}
