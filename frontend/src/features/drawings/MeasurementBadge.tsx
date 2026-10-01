import { Badge, type BadgeTone } from '../../components/Badge'
import type { MeasurementState } from '../../types/api'

// The label always carries the meaning; the tone is only reinforcement.
const STATE: Record<MeasurementState, { label: string; tone: BadgeTone }> = {
  indexed: { label: 'Not measured yet', tone: 'neutral' },
  queued: { label: 'Queued to measure', tone: 'info' },
  measuring: { label: 'Measuring', tone: 'info' },
  measured: { label: 'Measured', tone: 'success' },
  failed: { label: 'Measuring failed', tone: 'danger' },
}

export function MeasurementBadge({ state, errorMessage }: { state: MeasurementState; errorMessage?: string | null }) {
  const { label, tone } = STATE[state] ?? STATE.indexed
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="measurement-badge" data-state={state}>
      <Badge tone={tone}>{label}</Badge>
      {state === 'failed' && errorMessage && <span className="text-xs text-danger">{errorMessage}</span>}
    </span>
  )
}
