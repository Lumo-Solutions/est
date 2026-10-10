import type { AgentLine, AgentProposal } from './types'

export function proposal(over: Partial<AgentProposal> = {}): AgentProposal {
  return {
    id: 'pr1',
    run_id: 'run1',
    boq_line_item_id: 'b1',
    kind: 'candidate',
    candidate_ref: 'q:1',
    rate: 120,
    currency: 'AED',
    uom: 'm3',
    as_of: '2026-09-01',
    method: null,
    evidence: [
      { kind: 'cost_source', ref: 'q:1', label: 'Gulf Concrete quote Q-17', type: 'quotation' },
      { kind: 'quote', file_id: 'f1', path: 'Tender/Quotes/gulf.pdf', page: 3, quote: 'Ready-mix C40 at AED 120 per m3' },
    ],
    qty_check: { boq_quantity: 100, measured: 108, unit: 'm3', delta_pct: 8, class: 'within_tolerance' },
    flags: ['stale_rate'],
    confidence: 0.92,
    rationale: 'The quote matches the spec clause.',
    status: 'applied',
    applied_at: '2026-10-01T10:00:00Z',
    ...over,
  }
}

export function agentLine(over: Partial<AgentLine> = {}): AgentLine {
  const p = over.proposal === undefined ? proposal() : over.proposal
  return {
    line_id: 'l1aaaaaa-0000-0000-0000-000000000000',
    boq_line_item_id: 'b1',
    cost_source: 'agent_candidate',
    direct_unit_cost: 120,
    source_currency: 'AED',
    agent_proposal_id: p?.id ?? null,
    agent_confirmed_by: null,
    agent_confirmed_at: null,
    ...over,
    proposal: p,
  }
}

export const estimateLine = (over: Partial<AgentLine> = {}) =>
  agentLine({
    line_id: 'l2bbbbbb-0000-0000-0000-000000000000',
    cost_source: 'agent_estimate',
    proposal: proposal({
      id: 'pr2',
      kind: 'estimate',
      candidate_ref: null,
      method: 'Median of three similar lines, adjusted for volume',
      evidence: [{ kind: 'quote', file_id: 'f2', path: 'Tender/Spec/part3.pdf', page: 12, quote: 'Concrete grade C40' }],
      flags: ['agent_estimate', 'no_document_check'],
      confidence: 0.55,
    }),
    ...over,
  })
