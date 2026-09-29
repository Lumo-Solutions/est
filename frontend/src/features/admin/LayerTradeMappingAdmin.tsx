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
      <h2 className="text-lg font-semibold text-ink-title">Drawing layer-to-trade mapping</h2>
      <label htmlFor="layer-mapping-project" className="sr-only">
        Project
      </label>
      <select
        id="layer-mapping-project"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
        className="mt-2 rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
      >
        <option value="">-- Project --</option>
        {(projects ?? []).map((p) => (
          <option key={p.id} value={p.id}>{p.code}</option>
        ))}
      </select>

      {projectId && (
        <>
          <div className="relative overflow-x-auto rounded-card bg-white p-2">
            <table className="mt-2 w-full text-left text-sm">
              <thead className="border-b border-hairline font-medium text-muted">
                <tr><th className="py-1">Layer pattern</th><th>Trade</th></tr>
              </thead>
              <tbody>
                {(mappings ?? []).map((m) => (
                  <tr key={m.id} className="border-b border-row-rule hover:bg-canvas">
                    <td className="py-1">{m.layer_pattern}</td>
                    <td>{m.trade_node_id.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {canWrite ? (
            <div className="mt-2 flex items-end gap-2">
              <label htmlFor="layer-mapping-pattern" className="sr-only">
                Layer pattern
              </label>
              <input
                id="layer-mapping-pattern"
                placeholder="Layer pattern (e.g. C-ROAD-*)"
                value={layerPattern}
                onChange={(e) => setLayerPattern(e.target.value)}
                className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
              />
              <label htmlFor="layer-mapping-trade" className="sr-only">
                Trade
              </label>
              <select
                id="layer-mapping-trade"
                value={tradeNodeId}
                onChange={(e) => setTradeNodeId(e.target.value)}
                className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
              >
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
                className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Add mapping (whole-set replace)
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted">Your role can view mappings but not change them.</p>
          )}
          {replace.isError && (
            <p role="alert" className="mt-1 text-sm text-danger">
              {replace.error.message}
            </p>
          )}
        </>
      )}
    </div>
  )
}
