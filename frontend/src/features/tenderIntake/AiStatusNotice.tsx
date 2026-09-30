import type { TreeSummary } from './types'

const FALLBACK = 'AI is unavailable, so files are classified by the built-in rules and need your check.'

// Non-blocking: uploads keep working, the rules classifier decides and a person checks.
export function AiStatusNotice({ summary }: { summary: TreeSummary }) {
  if (summary.ai_available) return null
  return (
    <div role="status" className="mt-6 rounded-card border border-amber-300 bg-warning-subtle px-5 py-3 text-sm text-amber-900">
      <p className="font-medium">AI classification is off</p>
      <p className="mt-0.5">{summary.ai_message || FALLBACK}</p>
    </div>
  )
}
