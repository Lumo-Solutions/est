import type { BadgeTone } from '../../components/Badge'
import type { AgentRunStatus, AgentSectionStatus, StopReason } from './types'

// Roles that may start, confirm, pause/resume/cancel and chat (the server enforces it; this only decides what to show).
export const AGENT_ROLES = ['lead_estimator', 'procurement_head', 'bd_director', 'managing_director'] as const
export const READ_ONLY_REASON = 'Only a lead estimator, procurement head, BD director or the managing director can do this.'

export const RUN_STATUS_LABEL: Record<AgentRunStatus, string> = {
  queued: 'Queued',
  planning: 'Planning',
  running: 'Running',
  awaiting_confirm: 'Waiting for your OK on the cost',
  paused: 'Paused',
  done: 'Done',
  stopped_limit: 'Stopped at a limit',
  failed: 'Failed',
  cancelled: 'Cancelled',
  blocked: 'Blocked',
}

export const RUN_STATUS_TONE: Record<AgentRunStatus, BadgeTone> = {
  queued: 'neutral',
  planning: 'info',
  running: 'info',
  awaiting_confirm: 'warning',
  paused: 'warning',
  done: 'success',
  stopped_limit: 'warning',
  failed: 'danger',
  cancelled: 'neutral',
  blocked: 'danger',
}

export const STOP_REASON_LABEL: Record<StopReason, string> = {
  steps: 'step limit',
  cost: 'cost limit',
  budget: 'budget limit',
  time: 'time limit',
}

export function sectionStatusLabel(status: AgentSectionStatus, stop: StopReason | null): string {
  switch (status) {
    case 'pending':
      return 'Pending'
    case 'reading':
      return 'Reading'
    case 'done':
      return 'Done'
    case 'stopped_limit':
      return stop ? `Stopped at the ${STOP_REASON_LABEL[stop]}` : 'Stopped at a limit'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
  }
}

export const SECTION_TONE: Record<AgentSectionStatus, BadgeTone> = {
  pending: 'neutral',
  reading: 'info',
  done: 'success',
  stopped_limit: 'warning',
  failed: 'danger',
  cancelled: 'neutral',
}

export const TOOL_LABEL: Record<string, string> = {
  boq_outline: 'Read BOQ outline',
  boq_lines: 'Read BOQ lines',
  list_folder: 'List folder',
  search_files: 'Search files',
  file_info: 'File info',
  read_text: 'Read text',
  read_sheet: 'Read sheet',
  view_page: 'View page',
  read_title_block: 'Read title block',
  get_measurements: 'Get measurements',
  verify_lines: 'Verify lines',
  cost_candidates: 'Find cost candidates',
  propose_line: 'Propose line',
  finish_section: 'Finish section',
  run_status: 'Check run status',
  explain_line: 'Explain line',
  rerun_section: 'Re-run section',
  invalid: 'Invalid step',
}
export const toolLabel = (tool: string) => TOOL_LABEL[tool] ?? tool.replace(/_/g, ' ')

export const formatUsd = (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`

export function formatSeconds(s: number | undefined): string {
  if (s == null) return '-'
  if (s < 60) return `${Math.round(s)} s`
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`
}

export const documentHref = (documentId: string, page: number | null) =>
  `/api/v1/tender-documents/${documentId}/download${page ? `#page=${page}` : ''}`
