import { Badge } from '../../components/Badge'
import { confidenceTone, flagInfo, formatConfidence } from './constants'
import { sourceLabel } from './text'
import type { AgentLine } from './types'

/** The source badge of an agent line. With onOpen it is a button that opens the evidence drawer. */
export function AgentSourceBadge({ line, onOpen }: { line: AgentLine; onOpen?: (lineId: string) => void }) {
  const badge = (
    <Badge tone={line.agent_confirmed_by ? 'success' : line.cost_source === 'agent_estimate' ? 'warning' : 'info'}>
      {sourceLabel(line)}
    </Badge>
  )
  if (!onOpen) return badge
  return (
    <button
      type="button"
      onClick={() => onOpen(line.line_id)}
      title="Show the evidence for this agent line"
      className="inline-flex items-center rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      {badge}
      <span className="sr-only">Show evidence for line {line.line_id.slice(0, 8)}</span>
    </button>
  )
}

export function ConfidenceChip({ confidence }: { confidence: number | null | undefined }) {
  if (confidence == null) return null
  return (
    <Badge tone={confidenceTone(confidence)}>
      <span className="sr-only">Confidence </span>
      {formatConfidence(confidence)}
    </Badge>
  )
}

export function FlagChips({ flags }: { flags: string[] }) {
  return (
    <>
      {flags.map((flag) => {
        const info = flagInfo(flag)
        return (
          <span key={flag} title={info.meaning}>
            <Badge tone={info.tone}>{info.label}</Badge>
          </span>
        )
      })}
    </>
  )
}
