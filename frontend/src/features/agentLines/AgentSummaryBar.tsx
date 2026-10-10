import { useState } from 'react'
import { Button } from '../../components/Button'
import { useAgentConfirmBulk } from './api'
import { bulkResultText, unconfirmedText } from './text'
import type { AgentSummary, BulkConfirmResult } from './types'

/** Top-of-page banner while agent lines wait for a person, with Review and (lead+) Bulk confirm. */
export function AgentSummaryBar({
  settlementId,
  summary,
  draft,
  canAct,
  reviewing,
  onReview,
}: {
  settlementId: string
  summary: AgentSummary | undefined
  draft: boolean
  canAct: boolean
  reviewing: boolean
  onReview: () => void
}) {
  const bulk = useAgentConfirmBulk(settlementId)
  const [result, setResult] = useState<BulkConfirmResult | null>(null)
  const unconfirmed = draft ? (summary?.unconfirmed ?? 0) : 0

  return (
    <>
      {unconfirmed > 0 && (
        <div role="status" className="mt-4 flex flex-wrap items-center gap-3 rounded-card bg-warning-subtle px-4 py-3 text-sm text-amber-800">
          <span className="font-medium">{unconfirmedText(unconfirmed)}</span>
          <Button variant="secondary" size="sm" aria-pressed={reviewing} onClick={onReview}>
            {reviewing ? 'Show all lines' : 'Review'}
          </Button>
          {canAct && (
            <Button
              variant="secondary"
              size="sm"
              loading={bulk.isPending}
              onClick={() => bulk.mutate(undefined, { onSuccess: setResult })}
            >
              Bulk confirm
            </Button>
          )}
        </div>
      )}
      {result && (
        <p role="status" className="mt-2 text-sm text-ink">
          {bulkResultText(result)}
        </p>
      )}
      {bulk.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {bulk.error.message}
        </p>
      )}
    </>
  )
}
