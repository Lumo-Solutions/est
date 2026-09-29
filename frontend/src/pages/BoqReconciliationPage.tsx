import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { SkeletonRows } from '../components/Skeleton'
import {
  useBoqItems,
  useLinkMeasurement,
  useMeasurementLinks,
  useMeasurementSuggestions,
  useReconcileBoqItem,
  useRecordSemanticFeedback,
  useUnlinkedMeasurements,
  useUnlinkMeasurement,
} from '../features/boq/api'
import { BoqReconciliationGrid } from '../features/boq/BoqReconciliationGrid'
import type { BoqLineItemOut } from '../types/api'

function ItemDetailPanel({ projectId, item }: { projectId: string; item: BoqLineItemOut }) {
  const { data: links } = useMeasurementLinks(item.id)
  const { data: suggestions } = useMeasurementSuggestions(item.id)
  const linkMeasurement = useLinkMeasurement(projectId, item.id)
  const unlinkMeasurement = useUnlinkMeasurement(projectId, item.id)
  const reconcile = useReconcileBoqItem(projectId)
  const feedback = useRecordSemanticFeedback()

  return (
    <div className="border-t border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-800">
        {item.item_no} -- {item.description}
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        Variance: {item.variance ?? '--'} ({item.variance_pct?.toFixed(1) ?? '--'}%) {item.discrepancy_class ?? ''}
      </p>
      <button
        type="button"
        onClick={() => reconcile.mutate(item.id)}
        disabled={reconcile.isPending}
        className="mt-2 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 transition-colors duration-150 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        Reconcile
      </button>
      {reconcile.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {reconcile.error.message}
        </p>
      )}

      <h4 className="mt-3 text-xs font-semibold uppercase text-slate-500">Linked measurements</h4>
      {(links ?? []).length === 0 && <p className="text-xs text-slate-500">None linked yet.</p>}
      <ul className="mt-1 space-y-1">
        {(links ?? []).map((m) => (
          <li key={m.id} className="flex items-center justify-between text-xs">
            <span>
              {m.kind}: {m.effective_value} {m.unit}
            </span>
            <button
              type="button"
              onClick={() => unlinkMeasurement.mutate(m.id)}
              className="rounded text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Unlink
            </button>
          </li>
        ))}
      </ul>
      {unlinkMeasurement.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {unlinkMeasurement.error.message}
        </p>
      )}

      <h4 className="mt-3 text-xs font-semibold uppercase text-slate-500">Suggested links</h4>
      {(suggestions ?? []).length === 0 && <p className="text-xs text-slate-500">No suggestions.</p>}
      {/* linkMeasurement can genuinely fail (e.g. a suggestion whose
          measurement unit isn't dimensionally compatible with this BOQ
          item's UoM -- the backend validates that and 422s) -- found live
          during the finish-brief follow-up's second walkthrough: clicking
          Accept on exactly such a suggestion silently did nothing at all,
          the same "an action a role/state can't perform stays enabled and
          fails 100% silently" bug class flagged repeatedly in
          docs/ui-qa/issues.md. */}
      {linkMeasurement.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {linkMeasurement.error.message}
        </p>
      )}
      <ul className="mt-1 space-y-1">
        {(suggestions ?? []).map((s) => (
          <li key={s.target_id} className="flex items-center justify-between text-xs">
            <span>
              measurement {s.target_id.slice(0, 8)} (score {(s.final_score * 100).toFixed(0)}%)
            </span>
            <span className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  // Record the "accepted" feedback signal only once the
                  // link itself actually succeeds -- previously both fired
                  // unconditionally, so a suggestion the backend rejects
                  // (e.g. dimensionally-incompatible units) still recorded
                  // a false "accepted" outcome for semantic-match tuning,
                  // on top of the Accept button silently doing nothing.
                  linkMeasurement.mutate(s.target_id, {
                    onSuccess: () =>
                      feedback.mutate({
                        match_type: 'boq_measurement',
                        query_embedding_source_id: item.id,
                        target_id: s.target_id,
                        outcome: 'accepted',
                      }),
                  })
                }}
                disabled={linkMeasurement.isPending}
                className="rounded text-emerald-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 disabled:opacity-50"
              >
                Accept
              </button>
              <button
                type="button"
                onClick={() =>
                  feedback.mutate({
                    match_type: 'boq_measurement',
                    query_embedding_source_id: item.id,
                    target_id: s.target_id,
                    outcome: 'rejected',
                  })
                }
                className="rounded text-danger hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Reject
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function UnlinkedMeasurementsPanel({ projectId }: { projectId: string }) {
  const { data: unlinked } = useUnlinkedMeasurements(projectId)
  return (
    <div className="border-t border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Unlinked measurements</h3>
      {(unlinked ?? []).length === 0 && <p className="mt-1 text-xs text-slate-500">None.</p>}
      <ul className="mt-1 space-y-1 text-xs text-slate-600">
        {(unlinked ?? []).map((m) => (
          <li key={m.id}>
            {m.kind}: {m.effective_value} {m.unit} (confidence {(m.confidence * 100).toFixed(0)}%)
          </li>
        ))}
      </ul>
    </div>
  )
}

export function BoqReconciliationPage() {
  const { projectId } = useParams()
  const { data: items, isLoading, isError, error } = useBoqItems(projectId)
  const [selectedItem, setSelectedItem] = useState<BoqLineItemOut | null>(null)

  return (
    <div className="flex h-[calc(100vh-49px)] flex-col">
      <div className="flex items-center justify-between p-4">
        <h1 className="text-xl font-semibold text-slate-800">BOQ reconciliation</h1>
        {projectId && (
          <Link
            to={`/projects/${projectId}/boq/import`}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Import BOQ
          </Link>
        )}
      </div>
      {isError && (
        <p role="alert" className="px-4 text-danger">
          {error.message}
        </p>
      )}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1">
          {isLoading ? (
            <div className="p-4">
              <SkeletonRows count={8} />
            </div>
          ) : (
            <BoqReconciliationGrid rows={items ?? []} onRowClick={setSelectedItem} />
          )}
        </div>
        <div className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white">
          {selectedItem && projectId && <ItemDetailPanel projectId={projectId} item={selectedItem} />}
          {projectId && <UnlinkedMeasurementsPanel projectId={projectId} />}
        </div>
      </div>
    </div>
  )
}
