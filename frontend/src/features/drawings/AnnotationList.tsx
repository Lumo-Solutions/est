import type { DrawingAnnotationOut } from '../../types/api'
import { Badge } from '../../components/Badge'

// The annotations the AI read off one sheet. Every row is labelled "AI-read"
// so nobody mistakes them for a human-entered or measured value.
export function AnnotationList({ annotations }: { annotations: DrawingAnnotationOut[] }) {
  if (annotations.length === 0) {
    return <p className="text-sm text-muted">No annotations read for this sheet.</p>
  }
  return (
    <ul className="divide-y divide-row-rule text-sm">
      {annotations.map((a) => (
        <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
          <Badge tone="info">AI-read</Badge>
          <span className="text-ink">{a.text}</span>
          {a.kind && <span className="text-muted">{a.kind}</span>}
          {a.value != null && (
            <span className="tabular-nums">
              {a.value}
              {a.unit ? ` ${a.unit}` : ''}
            </span>
          )}
          {a.material && <span className="text-muted">{a.material}</span>}
        </li>
      ))}
    </ul>
  )
}
