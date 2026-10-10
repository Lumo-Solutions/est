// Shapes of docs/boq-agent/api-contract.md. Kept here (not in types/api.ts) on purpose.
export type AgentRunStatus =
  | 'queued'
  | 'planning'
  | 'running'
  | 'awaiting_confirm'
  | 'paused'
  | 'done'
  | 'stopped_limit'
  | 'failed'
  | 'cancelled'
  | 'blocked'

export type RunAction = 'confirm' | 'pause' | 'resume' | 'cancel'

export type AgentSectionStatus = 'pending' | 'reading' | 'done' | 'stopped_limit' | 'failed' | 'cancelled'
export type StopReason = 'steps' | 'cost' | 'budget' | 'time'

export interface AgentLimits {
  max_steps: number
  max_page_views: number
  max_usd: number
}

export interface AgentEstimate {
  provider: string
  model: string | null
  external: boolean
  sections: number
  steps: number
  page_views: number
  usd: number
  usd_uncapped: number
  usd_cap: number
  unverified_price: boolean
  note: string | null
}

export interface AgentPlanSection {
  section_id: string
  folders: string[]
  queries: string[]
  why: string | null
}

export interface AgentPlan {
  summary: string | null
  sections: AgentPlanSection[]
}

export interface AgentRunSummary {
  applied?: { applied?: number; skipped_person_set?: number; [k: string]: number | undefined }
  sections?: Record<string, number>
  files_read?: number
  files_in_pack?: number
  files_read_ratio?: number
  proposals?: number
  seconds?: number
  lines_without_proposal?: number
}

export interface AgentRun {
  id: string
  project_id: string
  kind: string
  settlement_id: string | null
  status: AgentRunStatus
  scope: unknown
  limits: AgentLimits | null
  estimate: AgentEstimate | null
  plan: AgentPlan | null
  summary: AgentRunSummary | null
  provider: string | null
  steps_total: number
  page_views: number
  ai_calls: number
  cost_usd: number
  error: string | null
  started_by: string | null
  confirmed_by: string | null
  confirmed_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface CoverageFileRead {
  file_id: string
  path: string
  pages: number[]
}
export interface CoverageNotRead {
  file_id: string
  path: string
  why_found: string | null
  why_not_read: string | null
}
export interface AgentCoverage {
  files_read: CoverageFileRead[]
  found_not_read: CoverageNotRead[]
  lines_total: number
  lines_proposed: number
  lines_without_proposal: string[]
  lines_cost_source_only: number
}

export interface AgentSection {
  id: string
  section_item_id: string | null
  label: string
  seq: number
  status: AgentSectionStatus
  line_count: number
  steps: number
  plan: unknown
  summary: unknown
  coverage: AgentCoverage | null
  stop_reason: StopReason | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface AgentRunDetail extends AgentRun {
  sections: AgentSection[]
}

export interface AgentRunCreate {
  sections?: string[]
  line_ids?: string[]
  notes?: Record<string, string>
  limits?: Partial<AgentLimits>
  create_draft?: boolean
}

export interface AgentFileRef {
  document_id: string
  filename: string
  page: number | null
}

export interface AgentStep {
  id: string
  run_id: string
  section_id: string | null
  seq: number
  tool: string
  args: unknown
  note: string | null
  ok: boolean
  result_summary: string | null
  file_refs: AgentFileRef[]
  tokens_in: number
  tokens_out: number
  cost_usd: number
  injection: boolean
  created_at: string
}

export interface AgentSummaryOut {
  agent_lines: number
  unconfirmed: number
}

export interface ChatMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | string
  content: string
  run_id: string | null
  created_at: string
}
export interface ChatPostOut {
  conversation_id: string
  message: ChatMessage
  run_id: string
}
export interface Conversation {
  id: string
  title: string | null
  created_at: string
}

const TERMINAL: AgentRunStatus[] = ['done', 'stopped_limit', 'failed', 'cancelled', 'blocked']
const ACTIVE: AgentRunStatus[] = ['queued', 'planning', 'running', 'awaiting_confirm']
export const isTerminal = (s: AgentRunStatus | undefined) => !!s && TERMINAL.includes(s)
export const isActive = (s: AgentRunStatus | undefined) => !!s && ACTIVE.includes(s)
