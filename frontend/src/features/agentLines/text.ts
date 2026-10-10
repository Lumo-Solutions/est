import type { AgentLine, BulkConfirmResult } from './types'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function unconfirmedText(n: number): string {
  return `${plural(n, 'agent line needs', 'agent lines need')} confirmation before submit`
}

export function bulkResultText(r: BulkConfirmResult): string {
  const { estimate, blocked_or_low_confidence: blocked } = r.skipped
  const rest: string[] = []
  if (estimate > 0) rest.push(plural(estimate, 'estimate', 'estimates'))
  if (blocked > 0) rest.push(`${plural(blocked, 'low-confidence or blocked line', 'low-confidence or blocked lines')}`)
  const head = `${r.confirmed} confirmed`
  const verb = estimate + blocked === 1 ? 'needs' : 'need'
  return rest.length > 0 ? `${head}; ${rest.join(' and ')} ${verb} one-by-one review` : head
}

export function sourceLabel(line: Pick<AgentLine, 'cost_source' | 'agent_confirmed_by'>): string {
  if (line.agent_confirmed_by) return 'Confirmed'
  return line.cost_source === 'agent_estimate' ? 'Agent: estimate' : 'Agent: source'
}
