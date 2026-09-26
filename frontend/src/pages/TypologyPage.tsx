import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useBoqItems } from '../features/boq/api'
import {
  useConfirmTypologyCluster,
  useDetectTypologyClusters,
  useRejectTypologyCluster,
  useTypologyClusterInstances,
  useTypologyClusters,
  useTypologyRollup,
  useTypologyVariantDeltas,
} from '../features/typology/api'
import type { ConfirmClusterDeltaIn, ConfirmClusterGroupIn, TypologyClusterStatus } from '../types/api'

const STATUS_STYLES: Record<TypologyClusterStatus, string> = {
  proposed: 'bg-amber-100 text-amber-800',
  confirmed: 'bg-green-100 text-green-800',
  rejected: 'bg-slate-100 text-slate-500',
}

function ConfirmForm({
  projectId,
  clusterId,
  groups,
  onDone,
}: {
  projectId: string
  clusterId: string
  groups: ConfirmClusterGroupIn[]
  onDone: () => void
}) {
  const [labels, setLabels] = useState(groups.map((g) => g.group_label))
  const [masterIndex, setMasterIndex] = useState(0)
  const [deltas, setDeltas] = useState<ConfirmClusterDeltaIn[]>([])
  const { data: boqItems } = useBoqItems(projectId)
  const confirm = useConfirmTypologyCluster(projectId, clusterId)

  const addDelta = () =>
    setDeltas((prev) => [...prev, { group_label: labels[0] ?? '', description: '', quantity_delta: null, unit: null }])

  return (
    <div className="mt-4 rounded border border-slate-200 p-4">
      <h4 className="text-sm font-semibold text-slate-800">Confirm cluster</h4>
      <table className="mt-2 w-full text-left text-sm">
        <thead className="text-slate-500">
          <tr>
            <th>Master</th>
            <th>Group label</th>
            <th>Instances</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, i) => (
            <tr key={i}>
              <td>
                <input type="radio" name="master" checked={masterIndex === i} onChange={() => setMasterIndex(i)} />
              </td>
              <td>
                <input
                  value={labels[i]}
                  onChange={(e) => setLabels((prev) => prev.map((l, j) => (j === i ? e.target.value : l)))}
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                />
              </td>
              <td>{g.handles.length}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h5 className="mt-3 text-xs font-semibold uppercase text-slate-500">Variant deltas</h5>
      {deltas.map((delta, i) => (
        <div key={i} className="mt-1 flex flex-wrap items-end gap-2">
          <select
            value={delta.group_label}
            onChange={(e) => setDeltas((prev) => prev.map((d, j) => (j === i ? { ...d, group_label: e.target.value } : d)))}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {labels.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <input
            placeholder="Description"
            value={delta.description}
            onChange={(e) => setDeltas((prev) => prev.map((d, j) => (j === i ? { ...d, description: e.target.value } : d)))}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <select
            value={delta.boq_line_item_id ?? ''}
            onChange={(e) =>
              setDeltas((prev) => prev.map((d, j) => (j === i ? { ...d, boq_line_item_id: e.target.value || null } : d)))
            }
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">-- BOQ item --</option>
            {(boqItems ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.item_no}
              </option>
            ))}
          </select>
          <input
            type="number"
            step="any"
            placeholder="Qty delta"
            value={delta.quantity_delta ?? ''}
            onChange={(e) =>
              setDeltas((prev) => prev.map((d, j) => (j === i ? { ...d, quantity_delta: Number(e.target.value) } : d)))
            }
            className="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            placeholder="Unit"
            value={delta.unit ?? ''}
            onChange={(e) => setDeltas((prev) => prev.map((d, j) => (j === i ? { ...d, unit: e.target.value } : d)))}
            className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
      ))}
      <button type="button" onClick={addDelta} className="mt-1 text-xs text-slate-600 underline">
        + add delta
      </button>

      <div className="mt-3">
        <button
          type="button"
          disabled={confirm.isPending}
          onClick={() =>
            confirm.mutate(
              {
                groups: groups.map((g, i) => ({ group_label: labels[i], handles: g.handles })),
                master_group_label: labels[masterIndex],
                deltas,
              },
              { onSuccess: onDone },
            )
          }
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Confirm cluster
        </button>
        {confirm.isError && <p className="mt-1 text-sm text-red-600">{confirm.error.message}</p>}
      </div>
    </div>
  )
}

function ClusterDetail({ projectId, clusterId, status }: { projectId: string; clusterId: string; status: TypologyClusterStatus }) {
  const { data: instances } = useTypologyClusterInstances(clusterId)
  const { data: deltas } = useTypologyVariantDeltas(clusterId)
  const { data: rollup } = useTypologyRollup(clusterId, status === 'confirmed')
  const [confirming, setConfirming] = useState(false)
  const reject = useRejectTypologyCluster(projectId, clusterId)

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-800">Instances</h3>
      <ul className="mt-1 text-sm text-slate-600">
        {(instances ?? []).map((i) => (
          <li key={i.id}>
            {i.group_label}: {i.instance_count} instance(s), {i.source_handles.length} handle(s)
          </li>
        ))}
      </ul>

      {(deltas ?? []).length > 0 && (
        <>
          <h3 className="mt-3 text-sm font-semibold text-slate-800">Variant deltas</h3>
          <ul className="mt-1 text-sm text-slate-600">
            {(deltas ?? []).map((d) => (
              <li key={d.id}>
                {d.group_label}: {d.description} ({d.quantity_delta ?? 0} {d.unit ?? ''})
              </li>
            ))}
          </ul>
        </>
      )}

      {status === 'proposed' && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => setConfirming((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            {confirming ? 'Cancel' : 'Review and confirm'}
          </button>
          <button
            type="button"
            onClick={() => reject.mutate()}
            className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
          >
            Reject
          </button>
        </div>
      )}

      {confirming && instances && (
        <ConfirmForm
          projectId={projectId}
          clusterId={clusterId}
          groups={instances.map((i) => ({ group_label: i.group_label, handles: i.source_handles }))}
          onDone={() => setConfirming(false)}
        />
      )}

      {rollup && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-slate-800">Rollup ({rollup.total_instance_count} instances)</h3>
          <table className="mt-1 w-full text-left text-sm">
            <thead className="text-slate-500">
              <tr>
                <th>Item</th>
                <th>Master qty</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {rollup.items.map((item) => (
                <tr key={item.boq_line_item_id}>
                  <td>{item.item_no}</td>
                  <td>{item.master_quantity}</td>
                  <td>{item.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function TypologyPage() {
  const { projectId } = useParams()
  const { data: clusters, isLoading } = useTypologyClusters(projectId)
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null)
  const detect = useDetectTypologyClusters(projectId)

  const selectedCluster = clusters?.find((c) => c.id === selectedClusterId) ?? null

  return (
    <div className="p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Typology cluster review</h1>
        <button
          type="button"
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Detect clusters
        </button>
      </div>
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      <ul className="mt-4 space-y-1">
        {(clusters ?? []).map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => setSelectedClusterId(c.id)}
              className={`flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm ${
                c.id === selectedClusterId ? 'bg-slate-100' : 'hover:bg-slate-50'
              }`}
            >
              <span>
                {c.detection_method} / {c.detection_key}
              </span>
              <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[c.status]}`}>{c.status}</span>
            </button>
          </li>
        ))}
      </ul>

      {selectedCluster && projectId && (
        <ClusterDetail projectId={projectId} clusterId={selectedCluster.id} status={selectedCluster.status} />
      )}
    </div>
  )
}
