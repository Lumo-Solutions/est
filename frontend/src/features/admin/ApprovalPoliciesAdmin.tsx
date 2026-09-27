import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import type { ApprovalPolicyTierIn } from '../../types/api'
import { useApprovalPolicies, useCreateApprovalPolicy, useSetApprovalPolicyActive } from './api'

const ROLES = ['estimator', 'lead_estimator', 'procurement_head', 'bd_director', 'managing_director']

// Mirrors backend/app/api/v1/routes/approvals.py's _POLICY_ADMIN_ROLES --
// managing_director only (not even platform_admin or procurement_head).
const POLICY_ADMIN_ROLES = [Role.MANAGING_DIRECTOR]

export function ApprovalPoliciesAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...POLICY_ADMIN_ROLES)
  const { data: policies } = useApprovalPolicies()
  const createPolicy = useCreateApprovalPolicy()
  const setActive = useSetApprovalPolicyActive()

  const [entityType, setEntityType] = useState('')
  const [name, setName] = useState('')
  const [tiers, setTiers] = useState<ApprovalPolicyTierIn[]>([{ seq: 1, min_amount: 0, required_role: 'lead_estimator' }])

  const addTier = () =>
    setTiers((prev) => [...prev, { seq: prev.length + 1, min_amount: 0, required_role: 'lead_estimator' }])

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Approval policies</h2>
      <p className="mt-1 text-xs text-slate-500">
        Who has authority to approve what -- managing_director only. A new version never auto-deactivates the
        prior one; deactivate it explicitly below once the new one is ready.
      </p>

      {!canWrite && (
        <p className="mt-2 text-xs text-slate-500">Your role can view policies but not create or (de)activate them.</p>
      )}
      {canWrite && (
      <form
        className="mt-3 rounded border border-slate-200 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          createPolicy.mutate(
            { entity_type: entityType, name, tiers },
            {
              onSuccess: () => {
                setEntityType('')
                setName('')
                setTiers([{ seq: 1, min_amount: 0, required_role: 'lead_estimator' }])
              },
            },
          )
        }}
      >
        <div className="flex gap-2">
          <input placeholder="Entity type (e.g. bid_submission)" value={entityType} onChange={(e) => setEntityType(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
          <input placeholder="Policy name" value={name} onChange={(e) => setName(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
        </div>
        <h3 className="mt-2 text-xs font-semibold uppercase text-slate-500">Tiers</h3>
        {tiers.map((tier, i) => (
          <div key={i} className="mt-1 flex items-end gap-2">
            <input
              type="number"
              placeholder="Min amount"
              value={tier.min_amount ?? 0}
              onChange={(e) => setTiers((prev) => prev.map((t, j) => (j === i ? { ...t, min_amount: Number(e.target.value) } : t)))}
              className="w-32 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <input
              type="number"
              placeholder="Max amount (blank = open)"
              value={tier.max_amount ?? ''}
              onChange={(e) => setTiers((prev) => prev.map((t, j) => (j === i ? { ...t, max_amount: e.target.value ? Number(e.target.value) : null } : t)))}
              className="w-40 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <select
              value={tier.required_role}
              onChange={(e) => setTiers((prev) => prev.map((t, j) => (j === i ? { ...t, required_role: e.target.value } : t)))}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        ))}
        <button type="button" onClick={addTier} className="mt-1 text-xs text-slate-600 underline">
          + add tier
        </button>
        <div className="mt-2">
          <button type="submit" disabled={createPolicy.isPending} className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            Create new version
          </button>
        </div>
        {createPolicy.isError && <p className="mt-1 text-sm text-red-600">{createPolicy.error.message}</p>}
      </form>
      )}

      <table className="mt-4 w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-slate-500">
          <tr>
            <th>Entity type</th>
            <th>Name</th>
            <th>Version</th>
            <th>Mode</th>
            <th>Tiers</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {(policies ?? []).map((p) => (
            <tr key={p.id} className="border-b border-slate-100 align-top">
              <td>{p.entity_type}</td>
              <td>{p.name}</td>
              <td>v{p.version}</td>
              <td>{p.mode}</td>
              <td className="text-xs">
                {p.tiers.map((t) => `${t.min_amount}-${t.max_amount ?? '∞'}: ${t.required_role}`).join('; ')}
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={p.is_active}
                  disabled={!canWrite}
                  onChange={(e) => setActive.mutate({ policyId: p.id, data: { is_active: e.target.checked } })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {setActive.isError && <p className="mt-1 text-sm text-red-600">{setActive.error.message}</p>}
    </div>
  )
}
