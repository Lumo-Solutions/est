import { useAiStatus } from './api'

// Renders nothing while AI is usable (or still loading); otherwise a compact
// notice explaining why AI features are unavailable.
export function AiStatusNotice() {
  const { data: status } = useAiStatus()
  if (!status || status.available) return null
  return (
    <p role="status" className="rounded bg-warning-subtle px-3 py-2 text-sm text-amber-800">
      {status.message ?? 'AI is not available.'}
    </p>
  )
}
