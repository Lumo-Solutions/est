import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import { useProjects } from '../projects/api'
import { useBoqTolerances, useSetBoqTolerance } from './api'

// Mirrors backend/app/api/v1/routes/boq.py's _STRUCTURE_ROLES -- not
// platform_admin or estimator/bd_director.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

export function TolerancesAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: projects } = useProjects()
  const [projectId, setProjectId] = useState('')
  const { data: tolerances } = useBoqTolerances(projectId || undefined)
  const setTolerance = useSetBoqTolerance(projectId || undefined)
  const [pct, setPct] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">BOQ reconciliation tolerances</h2>
      <label htmlFor="tolerances-project" className="sr-only">
        Project
      </label>
      <select
        id="tolerances-project"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
        className="mt-2 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      >
        <option value="">-- Project --</option>
        {(projects ?? []).map((p) => (
          <option key={p.id} value={p.id}>{p.code}</option>
        ))}
      </select>

      {projectId && (
        <>
          <ul className="mt-2 text-sm text-slate-600">
            {(tolerances ?? []).map((t) => (
              <li key={t.id}>
                {t.trade_node_id ? `Trade ${t.trade_node_id.slice(0, 8)}` : 'Project default'}:{' '}
                <span className="tabular-nums">{t.tolerance_pct}%</span>
              </li>
            ))}
          </ul>
          {canWrite ? (
            <form
              className="mt-2 flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setTolerance.mutate({ tolerance_pct: Number(pct) }, { onSuccess: () => setPct('') })
              }}
            >
              <label htmlFor="tolerances-pct" className="sr-only">
                Project default tolerance percentage
              </label>
              <input
                id="tolerances-pct"
                type="number"
                step="any"
                placeholder="Project default tolerance %"
                value={pct}
                onChange={(e) => setPct(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1.5 text-sm tabular-nums focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              />
              <button
                type="submit"
                className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Set default
              </button>
            </form>
          ) : (
            <p className="mt-2 text-xs text-slate-500">Your role can view tolerances but not change them.</p>
          )}
          {setTolerance.isError && (
            <p role="alert" className="mt-1 text-sm text-danger">
              {setTolerance.error.message}
            </p>
          )}
        </>
      )}
    </div>
  )
}
