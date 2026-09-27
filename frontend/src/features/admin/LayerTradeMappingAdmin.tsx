import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import { useProjects } from '../projects/api'
import { useLayerTradeMappings, useReplaceLayerTradeMappings, useTaxonomyNodes } from './api'

// Mirrors backend/app/api/v1/routes/drawings.py's _TRADE_MAPPING_ROLES.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

export function LayerTradeMappingAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: projects } = useProjects()
  const [projectId, setProjectId] = useState('')
  const { data: mappings } = useLayerTradeMappings(projectId || undefined)
  const { data: taxonomyNodes } = useTaxonomyNodes()
  const replace = useReplaceLayerTradeMappings(projectId || undefined)

  const [layerPattern, setLayerPattern] = useState('')
  const [tradeNodeId, setTradeNodeId] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Drawing layer-to-trade mapping</h2>
      <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="mt-2 rounded border border-slate-300 px-2 py-1 text-sm">
        <option value="">-- Project --</option>
        {(projects ?? []).map((p) => (
          <option key={p.id} value={p.id}>{p.code}</option>
        ))}
      </select>

      {projectId && (
        <>
          <table className="mt-2 w-full text-left text-sm">
            <thead className="text-slate-500">
              <tr><th>Layer pattern</th><th>Trade</th></tr>
            </thead>
            <tbody>
              {(mappings ?? []).map((m) => (
                <tr key={m.id}><td>{m.layer_pattern}</td><td>{m.trade_node_id.slice(0, 8)}</td></tr>
              ))}
            </tbody>
          </table>

          {canWrite ? (
            <div className="mt-2 flex items-end gap-2">
              <input placeholder="Layer pattern (e.g. C-ROAD-*)" value={layerPattern} onChange={(e) => setLayerPattern(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" />
              <select value={tradeNodeId} onChange={(e) => setTradeNodeId(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm">
                <option value="">-- Trade --</option>
                {(taxonomyNodes ?? []).map((n) => (
                  <option key={n.id} value={n.id}>{n.name}</option>
                ))}
              </select>
              <button
                type="button"
                disabled={!layerPattern || !tradeNodeId}
                onClick={() => {
                  const next = [...(mappings ?? []).map((m) => ({ layer_pattern: m.layer_pattern, trade_node_id: m.trade_node_id })), { layer_pattern: layerPattern, trade_node_id: tradeNodeId }]
                  replace.mutate(next, { onSuccess: () => { setLayerPattern(''); setTradeNodeId('') } })
                }}
                className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                Add mapping (whole-set replace)
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-500">Your role can view mappings but not change them.</p>
          )}
          {replace.isError && <p className="mt-1 text-sm text-red-600">{replace.error.message}</p>}
        </>
      )}
    </div>
  )
}
