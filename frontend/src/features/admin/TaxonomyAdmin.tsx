import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import { useCreateTaxonomyNode, useMoveTaxonomyNode, useTaxonomyNodes, useUpdateTaxonomyNode } from './api'

// Mirrors backend/app/api/v1/routes/taxonomy.py's _WRITE_ROLES -- notably
// NOT platform_admin, even though AdminPage is nav-gated to admin/md.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

export function TaxonomyAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: nodes } = useTaxonomyNodes(false)
  const createNode = useCreateTaxonomyNode()
  const updateNode = useUpdateTaxonomyNode()
  const moveNode = useMoveTaxonomyNode()

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [parentId, setParentId] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Trade taxonomy</h2>
      {!canWrite && (
        <p className="mt-1 text-xs text-slate-500">Your role can view the taxonomy but not edit it.</p>
      )}
      {canWrite && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            createNode.mutate(
              { code, name, parent_id: parentId || null },
              { onSuccess: () => { setCode(''); setName('') } },
            )
          }}
        >
          <input placeholder="Code" value={code} onChange={(e) => setCode(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
          <select value={parentId} onChange={(e) => setParentId(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm">
            <option value="">-- No parent (root) --</option>
            {(nodes ?? []).map((n) => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>
          <button type="submit" className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white">
            Add node
          </button>
        </form>
      )}
      {createNode.isError && <p className="mt-1 text-sm text-red-600">{createNode.error.message}</p>}
      {updateNode.isError && <p className="mt-1 text-sm text-red-600">{updateNode.error.message}</p>}
      {moveNode.isError && <p className="mt-1 text-sm text-red-600">{moveNode.error.message}</p>}

      <table className="mt-4 w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-slate-500">
          <tr>
            <th>Path</th>
            <th>Code</th>
            <th>Name</th>
            <th>Active</th>
            <th>Move to</th>
          </tr>
        </thead>
        <tbody>
          {(nodes ?? []).map((n) => (
            <tr key={n.id} className="border-b border-slate-100">
              <td className="font-mono text-xs">{n.path}</td>
              <td>{n.code}</td>
              <td>{n.name}</td>
              <td>
                <input
                  type="checkbox"
                  checked={n.is_active}
                  disabled={!canWrite}
                  onChange={(e) => updateNode.mutate({ nodeId: n.id, data: { is_active: e.target.checked } })}
                />
              </td>
              <td>
                <select
                  defaultValue=""
                  disabled={!canWrite}
                  onChange={(e) => {
                    if (e.target.value) moveNode.mutate({ nodeId: n.id, newParentId: e.target.value })
                  }}
                  className="rounded border border-slate-300 px-1 py-0.5 text-xs disabled:opacity-50"
                >
                  <option value="">-- pick new parent --</option>
                  {(nodes ?? [])
                    .filter((candidate) => candidate.id !== n.id)
                    .map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
                    ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
